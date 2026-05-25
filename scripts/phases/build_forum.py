#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from common import ROOT, load_config, write_json

REPORT_JSON = ROOT / 'reports' / 'build_forum.json'
REPORT_MD = ROOT / 'reports' / 'build_forum.md'
PROGRESS_MD = ROOT / 'reports' / 'build_forum_progress.md'
SEED_SCRIPT = ROOT / 'scripts' / 'phases' / 'seed_synthetic_forum.rb'
DISCOURSE_SOURCE = Path('/home/agent/source/discourse')
DISCOURSE_WORKTREE = Path('/home/agent/worktrees/discourse-sql-ft')
DB_NAME = 'discourse_sql_ft'
DB_DUMP = ROOT / 'db' / 'snapshots' / 'synthetic-forum.sql.gz'
SCHEMA_OUT = ROOT / 'config' / 'schema.txt'

ENV_BASE = os.environ.copy()
ENV_BASE.update({
    'PATH': '/home/agent/.local/share/mise/shims:' + ENV_BASE.get('PATH', ''),
    'HOME': '/home/agent',
    'USER': 'agent',
    'LOGNAME': 'agent',
    'RAILS_ENV': 'development',
    'DISCOURSE_DEV_DB': DB_NAME,
    'BUNDLE_PATH': str(ROOT / 'vendor' / 'bundle'),
    'BUNDLE_WITHOUT': 'test:generic_import:migrations',
    'SKIP_EMBER_CLI_COMPILE': '1',
})

steps: list[dict] = []


def now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def progress(message: str) -> None:
    print(f'[{now()}] {message}', flush=True)
    PROGRESS_MD.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_MD.open('a', encoding='utf-8') as f:
        f.write(f'- `{now()}` {message}\n')


def run(cmd: list[str] | str, *, cwd: Path | None = None, env: dict | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    display = cmd if isinstance(cmd, str) else ' '.join(shlex.quote(x) for x in cmd)
    progress(f'RUN {display}')
    cp = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env or ENV_BASE,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        shell=isinstance(cmd, str),
    )
    out = cp.stdout or ''
    if out:
        print(out[-6000:], end='' if out.endswith('\n') else '\n')
    steps.append({'cmd': display, 'cwd': str(cwd or ROOT), 'exit_code': cp.returncode, 'tail': out[-4000:]})
    if check and cp.returncode != 0:
        raise RuntimeError(f'command failed exit={cp.returncode}: {display}')
    return cp


def install_system_packages() -> None:
    needed = ['postgresql', 'postgresql-libs', 'redis']
    missing = []
    for pkg in needed:
        cp = run(['pacman', '-Q', pkg], check=False, timeout=30)
        if cp.returncode != 0:
            missing.append(pkg)
    if missing:
        progress(f'Installing system packages: {", ".join(missing)}')
        run(['sudo', '-n', 'pacman', '-Sy', '--noconfirm', '--needed', *missing], timeout=1800)
    else:
        progress('System packages already installed')


def start_postgres() -> None:
    data = Path('/var/lib/postgres/data')
    run(['sudo', '-n', 'install', '-d', '-m', '700', '-o', 'postgres', '-g', 'postgres', str(data)], timeout=60)
    run(['sudo', '-n', 'install', '-d', '-m', '775', '-o', 'postgres', '-g', 'postgres', '/run/postgresql'], timeout=60)
    initialized = run(['sudo', '-n', '-u', 'postgres', '/usr/bin/test', '-s', str(data / 'PG_VERSION')], check=False, timeout=30).returncode == 0
    if not initialized:
        progress('Initializing PostgreSQL cluster')
        run(['sudo', '-n', '-u', 'postgres', 'initdb', '-D', str(data), '--locale=C.UTF-8'], timeout=300)
    status = run(['sudo', '-n', '-u', 'postgres', 'pg_ctl', '-D', str(data), 'status'], check=False, timeout=30)
    if status.returncode != 0:
        progress('Starting PostgreSQL')
        run(['sudo', '-n', '-u', 'postgres', 'pg_ctl', '-D', str(data), '-l', '/var/lib/postgres/postgresql.log', 'start'], timeout=120)
    else:
        progress('PostgreSQL already running')

    # Ensure OS user agent can connect via peer auth as DB role agent.
    role_exists = run(['sudo', '-n', '-u', 'postgres', 'psql', '-tAc', "SELECT 1 FROM pg_roles WHERE rolname='agent'"], timeout=30).stdout.strip()
    if role_exists != '1':
        run(['sudo', '-n', '-u', 'postgres', 'createuser', '-s', 'agent'], timeout=60)

    db_exists = run(['sudo', '-n', '-u', 'postgres', 'psql', '-tAc', f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'"], timeout=30).stdout.strip()
    if db_exists != '1':
        run(['createdb', DB_NAME], timeout=120)


def verify_pgvector() -> None:
    cp = run(['psql', '-d', 'postgres', '-Atc', "SELECT default_version FROM pg_available_extensions WHERE name='vector'"], check=False, timeout=30)
    if cp.returncode != 0 or not cp.stdout.strip():
        raise RuntimeError('pgvector extension is not available. Install pgvector before plugin migrations.')
    progress(f'pgvector available version {cp.stdout.strip()}')


def start_redis() -> None:
    if shutil.which('redis-cli') and run(['redis-cli', 'ping'], check=False, timeout=10).stdout.strip() == 'PONG':
        progress('Redis already running')
        return
    progress('Starting Redis daemon')
    run(['redis-server', '--daemonize', 'yes', '--port', '6379'], timeout=60)
    for _ in range(20):
        cp = run(['redis-cli', 'ping'], check=False, timeout=5)
        if cp.stdout.strip() == 'PONG':
            return
        time.sleep(1)
    raise RuntimeError('Redis did not respond to PING')


def prepare_worktree() -> None:
    if not DISCOURSE_SOURCE.exists():
        raise RuntimeError(f'Missing Discourse source at {DISCOURSE_SOURCE}')
    DISCOURSE_WORKTREE.parent.mkdir(parents=True, exist_ok=True)
    if not (DISCOURSE_WORKTREE / '.git').exists():
        run(['git', '-C', str(DISCOURSE_SOURCE), 'worktree', 'add', '-f', str(DISCOURSE_WORKTREE), 'HEAD'], timeout=300)
    else:
        progress(f'Using existing Discourse worktree {DISCOURSE_WORKTREE}')
    run(['git', 'status', '--short'], cwd=DISCOURSE_WORKTREE, timeout=60)


def bundle_install() -> None:
    run(['bundle', 'config', 'set', '--local', 'path', str(ROOT / 'vendor' / 'bundle')], cwd=DISCOURSE_WORKTREE, timeout=60)
    run(['bundle', 'config', 'set', '--local', 'without', 'test generic_import migrations'], cwd=DISCOURSE_WORKTREE, timeout=60)
    cp = run(['bundle', 'check'], cwd=DISCOURSE_WORKTREE, check=False, timeout=120)
    if cp.returncode != 0:
        run(['bundle', 'install', '--jobs', '8', '--retry', '3'], cwd=DISCOURSE_WORKTREE, timeout=7200)
    else:
        progress('Bundle already satisfied')


def pnpm_install() -> None:
    if not (DISCOURSE_WORKTREE / 'node_modules' / '.pnpm' / 'lock.yaml').exists():
        progress('Installing Discourse JS dependencies with pnpm for real asset processor inputs')
        run(['pnpm', 'install', '--frozen-lockfile'], cwd=DISCOURSE_WORKTREE, timeout=3600)
    else:
        progress('pnpm dependencies already installed')


def reset_and_migrate() -> None:
    progress(f'Resetting real Discourse development DB {DB_NAME}')
    run(['dropdb', '--if-exists', DB_NAME], timeout=120)
    run(['createdb', DB_NAME], timeout=120)
    run(['bundle', 'exec', 'rails', 'db:migrate'], cwd=DISCOURSE_WORKTREE, timeout=3600)


def write_seed_script(config: dict) -> None:
    data = config['data']
    SEED_SCRIPT.write_text(textwrap.dedent(f"""
        # frozen_string_literal: true
        require 'securerandom'
        require 'faker'

        srand(20260524)

        puts "Synthetic Discourse seed starting"

        # Relax limits for synthetic content while still going through real Discourse models.
        SiteSetting.min_post_length = 5
        SiteSetting.min_first_post_length = 5
        SiteSetting.min_topic_title_length = 8
        SiteSetting.tagging_enabled = true
        SiteSetting.create_tag_allowed_groups = Group::AUTO_GROUPS[:trust_level_0]

        admin = Discourse.system_user

        category_names = %w[support bugs features announcements dev integrations performance documentation community marketplace ux security]
        categories = category_names.first({data['categories']}).map.with_index do |name, i|
          Category.find_by(slug: name) || Category.create!(
            name: name.capitalize,
            slug: name,
            color: %w[0088CC CC3300 22AA66 FF9900 663399 009999 AA22AA 3366FF 999900 555555 111111 EE7722][i % 12],
            text_color: 'FFFFFF',
            user_id: admin.id
          )
        end

        tag_names = %w[login email upload mobile api search postgres redis rails ember performance memory billing sso oauth webhooks theme plugin moderation spam backup import export notifications digest markdown composer trust-level solved unread slow security accessibility docker cdn images video realtime jobs ai sql reporting analytics]
        tags = tag_names.first({data['tags']}).map {{ |name| Tag.find_by_name(name) || Tag.create!(name: name) }}

        first_names = %w[Alice Bob Carol Dave Erin Frank Grace Heidi Ivan Judy Mallory Niaj Olivia Peggy Rupert Sybil Trent Uma Victor Wendy Xavier Yara Zoe]
        last_names = %w[Stone Rivers Chen Patel Nguyen Cohen Smith Garcia Rossi Haddad Brown Wilson Taylor Martin Clark Lewis Walker Hall Young King]
        domains = %w[example.com mail.test forum.invalid discourse.local]

        users = []
        {data['users']}.times do |i|
          username = "user_#{{i.to_s.rjust(4, '0')}}"
          user = User.find_by(username: username)
          unless user
            user = User.create!(
              username: username,
              name: "#{{first_names.sample}} #{{last_names.sample}}",
              email: "#{{username}}@#{{domains.sample}}",
              password: SecureRandom.hex(16),
              active: true,
              approved: true,
              trust_level: [0, 1, 1, 1, 2, 2, 3].sample,
              created_at: rand(730).days.ago,
              last_seen_at: rand(120).days.ago
            )
            user.user_option.update!(email_messages_level: 0) if user.user_option
          end
          users << user
        end

        staff = users.sample(12)
        staff.first(4).each {{ |u| u.update!(admin: true) }}
        staff.drop(4).each {{ |u| u.update!(moderator: true) }}

        nouns = %w[login upload notification digest search webhook category tag profile mobile email postgres redis backup import export plugin theme composer markdown moderation permissions performance memory report dashboard]
        verbs = %w[fails hangs improves breaks confuses delays retries blocks redirects corrupts hides reveals indexes queues]
        adjectives = %w[slow strange intermittent urgent confusing helpful broken missing duplicate stale private public]
        bodies = [
          'I tried this on a fresh install and can reproduce it consistently.',
          'This started after the last update and several users mentioned it in support.',
          'The workaround is not obvious, so documenting the expected behavior would help.',
          'There may be a regression in the permission checks or background job processing.',
          'Performance gets worse when there are many replies and tags involved.',
          'I checked the logs and saw PostgreSQL and Redis activity around the same time.',
          'This affects mobile users more than desktop users according to the reports.',
          'Can staff confirm whether this is expected or a bug?'
        ]

        topic_target = {data['topics']}
        post_min = {data['posts_min']}
        post_max = {data['posts_max']}
        target_posts = rand(post_min..post_max)

        created_topics = []
        topic_target.times do |i|
          user = users.sample
          category = categories.sample
          title = "#{{adjectives.sample.capitalize}} #{{nouns.sample}} #{{verbs.sample}} when #{{nouns.sample}} changes #{{i}}"
          raw = ([bodies.sample] * rand(1..3)).join("\n\n") + "\n\nSynthetic case id #{{i}} about #{{nouns.sample}} and #{{nouns.sample}}."
          begin
            post = PostCreator.create!(user, title: title, raw: raw, category: category.id, skip_validations: true)
            topic = post.topic
            chosen_tags = tags.sample(rand(1..4))
            DiscourseTagging.tag_topic_by_names(topic, Guardian.new(admin), chosen_tags.map(&:name)) rescue nil
            days_ago = [[rand ** 2 * 540, 0].max, 540].min
            created_at = days_ago.days.ago - rand(86_400).seconds
            topic.update_columns(
              created_at: created_at,
              bumped_at: created_at + rand(0..30).days,
              views: rand(0..5000),
              closed: rand < 0.08,
              archived: rand < 0.03,
              visible: rand >= 0.02
            )
            post.update_columns(created_at: created_at)
            topic.update_columns(deleted_at: rand < 0.025 ? rand(1..60).days.ago : nil)
            created_topics << topic
          rescue => e
            warn "topic #{{i}} failed: #{{e.class}} #{{e.message}}"
          end
          puts "created topics #{{i + 1}}/#{{topic_target}}" if (i + 1) % 100 == 0
        end

        posts_created = Post.where.not(post_number: 1).count
        attempts = 0
        while posts_created < target_posts && attempts < target_posts * 3
          attempts += 1
          topic = created_topics.sample
          next unless topic && !topic.deleted_at
          user = users.sample
          raw = ([bodies.sample] * rand(1..2)).join("\n\n") + "\n\nReply about #{{nouns.sample}}, #{{nouns.sample}}, and #{{adjectives.sample}} behavior."
          begin
            post = PostCreator.create!(user, topic_id: topic.id, raw: raw, skip_validations: true)
            created_at = topic.created_at + rand(1..180).days + rand(86_400).seconds
            created_at = [created_at, Time.zone.now - rand(3600).seconds].min
            hidden = rand < 0.015
            deleted_at = rand < 0.02 ? created_at + rand(1..30).days : nil
            post.update_columns(created_at: created_at, hidden: hidden, deleted_at: deleted_at)
            topic.update_columns(bumped_at: [topic.bumped_at || topic.created_at, created_at].max)
            posts_created += 1
          rescue => e
            warn "reply failed: #{{e.class}} #{{e.message}}"
          end
          puts "created replies #{{posts_created}}/#{{target_posts}}" if posts_created % 500 == 0
        end

        posts = Post.where(deleted_at: nil).where(hidden: false).limit(20_000).to_a
        like_target = [posts.length * 2, 10_000].max
        like_target.times do |i|
          post = posts.sample
          user = users.sample
          next if post.user_id == user.id
          begin
            PostActionCreator.like(user, post)
          rescue StandardError
            nil
          end
          puts "likes attempted #{{i + 1}}/#{{like_target}}" if (i + 1) % 1000 == 0
        end

        # A few realistic reads/tracking rows.
        created_topics.sample([created_topics.length, 800].min).each do |topic|
          users.sample(rand(3..20)).each do |user|
            TopicUser.find_or_create_by!(topic: topic, user: user) do |tu|
              tu.posted = topic.posts.exists?(user_id: user.id)
              tu.last_read_post_number = rand(1..[topic.highest_post_number || 1, 1].max)
              tu.notification_level = TopicUser.notification_levels[:regular]
            end
          rescue StandardError
            nil
          end
        end

        Topic.find_each {{ |t| t.update_columns(posts_count: Post.where(topic_id: t.id, deleted_at: nil).count, like_count: Post.where(topic_id: t.id).sum(:like_count)) rescue nil }}


        # Private messages through real Discourse PostCreator.
        pm_count = 0
        80.times do |i|
          sender = users.sample
          recipients = (users - [sender]).sample(rand(1..3))
          begin
            PostCreator.create!(
              sender,
              title: "Private follow up about #{{nouns.sample}} #{{i}}",
              raw: "Can you check this private note about #{{nouns.sample}} and #{{nouns.sample}}? Synthetic PM #{{i}}.",
              archetype: Archetype.private_message,
              target_usernames: recipients.map(&:username).join(','),
              skip_validations: true
            )
            pm_count += 1
          rescue => e
            warn "pm failed: #{{e.class}} #{{e.message}}"
          end
        end
        puts "private messages created #{{pm_count}}"

        # Likes: use PostActionCreator, with a direct PostAction fallback so the real
        # Discourse like tables are populated even when creator guards reject synthetic users.
        like_created = 0
        posts_for_likes = Post.where(deleted_at: nil).where(hidden: false).where("user_id IS NOT NULL").limit(20_000).to_a
        12_000.times do |i|
          post = posts_for_likes.sample
          user = users.sample
          next if !post || post.user_id == user.id
          begin
            PostActionCreator.create(user, post, :like, created_at: post.created_at + rand(1..90).days)
          rescue StandardError
            begin
              PostAction.create!(
                user_id: user.id,
                post_id: post.id,
                post_action_type_id: PostActionType::LIKE_POST_ACTION_ID,
                created_at: post.created_at + rand(1..90).days,
                updated_at: post.created_at + rand(1..90).days
              )
            rescue StandardError
              next
            end
          end
          like_created += 1
          puts "likes created/attempted #{{like_created}}/12000" if like_created % 1000 == 0
        end
        Post.where(id: posts_for_likes.map(&:id)).find_each {{ |p| p.update_columns(like_count: PostAction.where(post_id: p.id, post_action_type_id: PostActionType::LIKE_POST_ACTION_ID).count) rescue nil }}

        # Reactions plugin content, if loaded.
        reaction_created = 0
        if defined?(DiscourseReactions::ReactionManager)
          SiteSetting.discourse_reactions_enabled = true
          SiteSetting.discourse_reactions_enabled_reactions = "heart|clap|laughing|open_mouth|cry|angry|thumbsup|thumbsdown|tada"
          SiteSetting.discourse_reactions_reaction_for_like = "heart" rescue nil
          reaction_values = %w[clap laughing open_mouth cry angry thumbsup thumbsdown tada]
          2500.times do
            post = posts_for_likes.sample
            user = users.sample
            next if !post || post.user_id == user.id
            begin
              DiscourseReactions::ReactionManager.new(reaction_value: reaction_values.sample, user: user, post: post).toggle!
              reaction_created += 1
            rescue StandardError
              nil
            end
          end
        end
        puts "reactions created #{{reaction_created}}"

        # Chat plugin content, if loaded.
        chat_messages_created = 0
        if defined?(Chat::Channel) && defined?(Chat::Message)
          SiteSetting.chat_enabled = true
          chat_categories = categories.sample([categories.length, 8].min)
          chat_channels = chat_categories.map.with_index do |category, i|
            Chat::CategoryChannel.find_or_create_by!(chatable: category) do |ch|
              ch.name = "#{{category.name}} Chat"
              ch.status = :open
              ch.threading_enabled = i.even? if ch.respond_to?(:threading_enabled=)
            end
          end

          20.times do
            dm_users = users.sample(rand(2..4))
            dm = Chat::DirectMessage.create!
            dm_users.each {{ |u| dm.direct_message_users.find_or_create_by!(user_id: u.id) }}
            ch = Chat::DirectMessageChannel.create!(chatable: dm, status: :open)
            dm_users.each {{ |u| ch.add(u) rescue nil }}
            chat_channels << ch
          rescue => e
            warn "chat dm channel failed: #{{e.class}} #{{e.message}}"
          end

          chat_phrases = [
            "Can someone check the latest deploy?",
            "The upload flow looks better today.",
            "I saw a postgres timeout in the logs.",
            "This feels like a permissions issue.",
            "Let's move the detailed answer back to the topic.",
            "Mobile users are still reporting notification delays.",
            "I can reproduce this with a fresh account.",
            "Ship it after one more smoke test."
          ]
          1500.times do |i|
            ch = chat_channels.sample
            user = users.sample
            begin
              ch.add(user) rescue nil
              m = Chat::Message.new(
                chat_channel: ch,
                user: user,
                last_editor_id: user.id,
                message: "#{{chat_phrases.sample}} Synthetic chat #{{i}} about #{{nouns.sample}}.",
                created_at: rand(180).days.ago,
                updated_at: rand(180).days.ago
              )
              m.cook if m.respond_to?(:cook)
              m.save!
              chat_messages_created += 1
              if rand < 0.25 && defined?(Chat::MessageReaction)
                users.sample(rand(1..4)).each do |reactor|
                  next if reactor.id == user.id
                  begin
                    ch.add(reactor) rescue nil
                    Chat::MessageReaction.create!(chat_message: m, user: reactor, emoji: %w[+1 tada heart laughing rocket].sample)
                  rescue StandardError
                    nil
                  end
                end
              end
            rescue => e
              warn "chat message failed: #{{e.class}} #{{e.message}}"
            end
          end
          chat_channels.each do |ch|
            last = ch.chat_messages.order(:created_at).last
            ch.update_columns(
              chat_messages_count: ch.chat_messages.count,
              user_count: ch.user_chat_channel_memberships.count,
              last_message_id: last&.id,
              last_message_created_at: last&.created_at
            ) rescue nil
          end
        end
        puts "chat messages created #{{chat_messages_created}}"

        summary = {{
          users: User.real.count,
          categories: Category.count,
          tags: Tag.count,
          topics: Topic.count,
          posts: Post.count,
          visible_topics: Topic.where(visible: true, deleted_at: nil).count,
          deleted_topics: Topic.where.not(deleted_at: nil).count,
          deleted_posts: Post.where.not(deleted_at: nil).count,
          user_actions: UserAction.count,
          post_actions: PostAction.count,
          topic_users: TopicUser.count,
          private_messages: Topic.where(archetype: Archetype.private_message).count,
          post_actions: PostAction.count,
          reactions: (defined?(DiscourseReactions::ReactionUser) ? DiscourseReactions::ReactionUser.count : 0),
          chat_channels: (defined?(Chat::Channel) ? Chat::Channel.count : 0),
          chat_messages: (defined?(Chat::Message) ? Chat::Message.count : 0),
          chat_message_reactions: (defined?(Chat::MessageReaction) ? Chat::MessageReaction.count : 0)
        }}
        puts "SYNTHETIC_FORUM_SUMMARY=#{{summary.to_json}}"
    """), encoding='utf-8')


def seed_forum(config: dict) -> None:
    write_seed_script(config)
    run(['bundle', 'exec', 'rails', 'runner', str(SEED_SCRIPT)], cwd=DISCOURSE_WORKTREE, timeout=7200)


def dump_and_schema() -> None:
    DB_DUMP.parent.mkdir(parents=True, exist_ok=True)
    run(f'pg_dump {shlex.quote(DB_NAME)} | gzip -9 > {shlex.quote(str(DB_DUMP))}', timeout=1800)
    schema_sql = run(['psql', '-d', DB_NAME, '-Atc', "SELECT table_name || '(' || string_agg(column_name, ', ' ORDER BY ordinal_position) || ')' FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('users','topics','posts','categories','tags','topic_tags','user_actions','topic_users','post_actions','chat_channels','chat_messages','chat_message_reactions','direct_message_channels','direct_message_users','discourse_reactions_reactions','discourse_reactions_reaction_users') GROUP BY table_name ORDER BY table_name"], timeout=120).stdout
    SCHEMA_OUT.write_text('-- Real Discourse PostgreSQL schema subset generated from migrated DB\n\n' + schema_sql, encoding='utf-8')


def write_reports() -> None:
    counts_sql = """
      SELECT json_build_object(
        'users', (SELECT count(*) FROM users),
        'categories', (SELECT count(*) FROM categories),
        'tags', (SELECT count(*) FROM tags),
        'topics', (SELECT count(*) FROM topics),
        'posts', (SELECT count(*) FROM posts),
        'topic_tags', (SELECT count(*) FROM topic_tags),
        'user_actions', (SELECT count(*) FROM user_actions),
        'post_actions', (SELECT count(*) FROM post_actions),
        'topic_users', (SELECT count(*) FROM topic_users)
      )::text
    """
    counts = run(['psql', '-d', DB_NAME, '-Atc', counts_sql], timeout=120).stdout.strip()
    report = {
        'db_name': DB_NAME,
        'discourse_worktree': str(DISCOURSE_WORKTREE),
        'db_dump': str(DB_DUMP),
        'schema': str(SCHEMA_OUT),
        'counts_json': counts,
        'steps': steps,
    }
    write_json(REPORT_JSON, report)
    REPORT_MD.write_text(textwrap.dedent(f"""
        # Build Forum Report

        - DB name: `{DB_NAME}`
        - Discourse worktree: `{DISCOURSE_WORKTREE}`
        - DB dump: `{DB_DUMP}`
        - Schema: `{SCHEMA_OUT}`

        Counts:

        ```json
        {counts}
        ```
    """).lstrip(), encoding='utf-8')


def main() -> int:
    config = load_config()
    PROGRESS_MD.write_text('# Build Forum Progress\n\n', encoding='utf-8')
    progress('Starting build_forum: real Discourse install, migration, and synthetic forum seeding')
    install_system_packages()
    start_postgres()
    verify_pgvector()
    start_redis()
    prepare_worktree()
    bundle_install()
    pnpm_install()
    reset_and_migrate()
    seed_forum(config)
    dump_and_schema()
    write_reports()
    progress('build_forum complete')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
