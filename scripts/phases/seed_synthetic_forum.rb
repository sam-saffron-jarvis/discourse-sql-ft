
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
        categories = category_names.first(12).map.with_index do |name, i|
          Category.find_by(slug: name) || Category.create!(
            name: name.capitalize,
            slug: name,
            color: %w[0088CC CC3300 22AA66 FF9900 663399 009999 AA22AA 3366FF 999900 555555 111111 EE7722][i % 12],
            text_color: 'FFFFFF',
            user_id: admin.id
          )
        end

        tag_names = %w[login email upload mobile api search postgres redis rails ember performance memory billing sso oauth webhooks theme plugin moderation spam backup import export notifications digest markdown composer trust-level solved unread slow security accessibility docker cdn images video realtime jobs ai sql reporting analytics]
        tags = tag_names.first(60).map { |name| Tag.find_by_name(name) || Tag.create!(name: name) }

        first_names = %w[Alice Bob Carol Dave Erin Frank Grace Heidi Ivan Judy Mallory Niaj Olivia Peggy Rupert Sybil Trent Uma Victor Wendy Xavier Yara Zoe]
        last_names = %w[Stone Rivers Chen Patel Nguyen Cohen Smith Garcia Rossi Haddad Brown Wilson Taylor Martin Clark Lewis Walker Hall Young King]
        domains = %w[example.com mail.test forum.invalid discourse.local]

        users = []
        500.times do |i|
          username = "user_#{i.to_s.rjust(4, '0')}"
          user = User.find_by(username: username)
          unless user
            user = User.create!(
              username: username,
              name: "#{first_names.sample} #{last_names.sample}",
              email: "#{username}@#{domains.sample}",
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
        staff.first(4).each { |u| u.update!(admin: true) }
        staff.drop(4).each { |u| u.update!(moderator: true) }

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

        topic_target = 1000
        post_min = 8000
        post_max = 15000
        target_posts = rand(post_min..post_max)

        created_topics = []
        topic_target.times do |i|
          user = users.sample
          category = categories.sample
          title = "#{adjectives.sample.capitalize} #{nouns.sample} #{verbs.sample} when #{nouns.sample} changes #{i}"
          raw = ([bodies.sample] * rand(1..3)).join("

") + "

Synthetic case id #{i} about #{nouns.sample} and #{nouns.sample}."
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
            warn "topic #{i} failed: #{e.class} #{e.message}"
          end
          puts "created topics #{i + 1}/#{topic_target}" if (i + 1) % 100 == 0
        end

        posts_created = Post.where.not(post_number: 1).count
        attempts = 0
        while posts_created < target_posts && attempts < target_posts * 3
          attempts += 1
          topic = created_topics.sample
          next unless topic && !topic.deleted_at
          user = users.sample
          raw = ([bodies.sample] * rand(1..2)).join("

") + "

Reply about #{nouns.sample}, #{nouns.sample}, and #{adjectives.sample} behavior."
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
            warn "reply failed: #{e.class} #{e.message}"
          end
          puts "created replies #{posts_created}/#{target_posts}" if posts_created % 500 == 0
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
          puts "likes attempted #{i + 1}/#{like_target}" if (i + 1) % 1000 == 0
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

        Topic.find_each { |t| t.update_posts_count; t.update_columns(like_count: Post.where(topic_id: t.id).sum(:like_count)) rescue nil }


        # Private messages through real Discourse PostCreator.
        pm_count = 0
        80.times do |i|
          sender = users.sample
          recipients = (users - [sender]).sample(rand(1..3))
          begin
            PostCreator.create!(
              sender,
              title: "Private follow up about #{nouns.sample} #{i}",
              raw: "Can you check this private note about #{nouns.sample} and #{nouns.sample}? Synthetic PM #{i}.",
              archetype: Archetype.private_message,
              target_usernames: recipients.map(&:username).join(','),
              skip_validations: true
            )
            pm_count += 1
          rescue => e
            warn "pm failed: #{e.class} #{e.message}"
          end
        end
        puts "private messages created #{pm_count}"

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
          puts "likes created/attempted #{like_created}/12000" if like_created % 1000 == 0
        end
        Post.where(id: posts_for_likes.map(&:id)).find_each { |p| p.update_columns(like_count: PostAction.where(post_id: p.id, post_action_type_id: PostActionType::LIKE_POST_ACTION_ID).count) rescue nil }

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
        puts "reactions created #{reaction_created}"

        # Chat plugin content, if loaded.
        chat_messages_created = 0
        if defined?(Chat::Channel) && defined?(Chat::Message)
          SiteSetting.chat_enabled = true
          chat_categories = categories.sample([categories.length, 8].min)
          chat_channels = chat_categories.map.with_index do |category, i|
            Chat::CategoryChannel.find_or_create_by!(chatable: category) do |ch|
              ch.name = "#{category.name} Chat"
              ch.status = :open
              ch.threading_enabled = i.even? if ch.respond_to?(:threading_enabled=)
            end
          end

          20.times do
            dm_users = users.sample(rand(2..4))
            dm = Chat::DirectMessage.create!
            dm_users.each { |u| dm.direct_message_users.find_or_create_by!(user_id: u.id) }
            ch = Chat::DirectMessageChannel.create!(chatable: dm, status: :open)
            dm_users.each { |u| ch.add(u) rescue nil }
            chat_channels << ch
          rescue => e
            warn "chat dm channel failed: #{e.class} #{e.message}"
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
                message: "#{chat_phrases.sample} Synthetic chat #{i} about #{nouns.sample}.",
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
              warn "chat message failed: #{e.class} #{e.message}"
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
        puts "chat messages created #{chat_messages_created}"

        summary = {
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
        }
        puts "SYNTHETIC_FORUM_SUMMARY=#{summary.to_json}"
