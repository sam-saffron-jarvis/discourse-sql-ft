# frozen_string_literal: true
require 'json'
require 'securerandom'

srand(20260524)
puts "Recovery enrichment starting"

SiteSetting.min_post_length = 5
SiteSetting.min_first_post_length = 5
SiteSetting.min_topic_title_length = 8
SiteSetting.tagging_enabled = true
SiteSetting.chat_enabled = true if SiteSetting.respond_to?(:chat_enabled=)

users = User.real.where(active: true).where.not(id: Discourse::SYSTEM_USER_ID).to_a
categories = Category.where(read_restricted: false).to_a
nouns = %w[login upload notification digest search webhook category tag profile mobile email postgres redis backup import export plugin theme composer markdown moderation permissions performance memory report dashboard]

raise "not enough users" if users.length < 10
raise "not enough categories" if categories.empty?

# Counter repair after previous crash.
Topic.find_each do |t|
  begin
    t.update_columns(
      posts_count: Post.where(topic_id: t.id, deleted_at: nil).count,
      like_count: Post.where(topic_id: t.id).sum(:like_count)
    )
  rescue => e
    warn "topic counter repair failed #{t.id}: #{e.class} #{e.message}"
  end
end

# PMs through real Discourse PostCreator.
pm_count = Topic.where(archetype: Archetype.private_message).count
if pm_count < 100
  (100 - pm_count).times do |i|
    sender = users.sample
    recipients = (users - [sender]).sample(rand(1..3))
    begin
      PostCreator.create!(
        sender,
        title: "Private follow up about #{nouns.sample} #{SecureRandom.hex(3)}",
        raw: "Can you check this private note about #{nouns.sample} and #{nouns.sample}? Synthetic PM recovery #{i}.",
        archetype: Archetype.private_message,
        target_usernames: recipients.map(&:username).join(','),
        skip_validations: true
      )
    rescue => e
      warn "pm failed: #{e.class} #{e.message}"
    end
  end
end
puts "pm_topics=#{Topic.where(archetype: Archetype.private_message).count}"

# Likes: already created, top up if necessary.
posts_for_likes = Post.where(deleted_at: nil).where(hidden: false).where("user_id IS NOT NULL").limit(20_000).to_a
like_count = PostAction.where(post_action_type_id: PostActionType::LIKE_POST_ACTION_ID).count
target_likes = 25_000
while like_count < target_likes
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
  like_count += 1
end
puts "likes=#{PostAction.where(post_action_type_id: PostActionType::LIKE_POST_ACTION_ID).count}"

# Discourse reactions.
reaction_created = 0
if defined?(DiscourseReactions::ReactionManager)
  SiteSetting.discourse_reactions_enabled = true
  SiteSetting.discourse_reactions_enabled_reactions = "heart|clap|laughing|open_mouth|cry|angry|thumbsup|thumbsdown|tada"
  SiteSetting.discourse_reactions_reaction_for_like = "heart" rescue nil
  reaction_values = %w[clap laughing open_mouth cry angry thumbsup thumbsdown tada]
  target = 2500
  current = defined?(DiscourseReactions::ReactionUser) ? DiscourseReactions::ReactionUser.count : 0
  attempts = 0
  while current < target && attempts < target * 10
    attempts += 1
    post = posts_for_likes.sample
    user = users.sample
    next if !post || post.user_id == user.id
    begin
      DiscourseReactions::ReactionManager.new(reaction_value: reaction_values.sample, user: user, post: post).toggle!
      current = DiscourseReactions::ReactionUser.count
      reaction_created += 1
    rescue StandardError
      nil
    end
  end
end
puts "reaction_users=#{defined?(DiscourseReactions::ReactionUser) ? DiscourseReactions::ReactionUser.count : 0} created=#{reaction_created}"

# Chat channels/messages/reactions.
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

  while Chat::DirectMessageChannel.count < 20
    dm_users = users.sample(rand(2..4))
    begin
      dm = Chat::DirectMessage.create!
      dm_users.each { |u| dm.direct_message_users.find_or_create_by!(user_id: u.id) }
      ch = Chat::DirectMessageChannel.create!(chatable: dm, status: :open)
      dm_users.each { |u| ch.add(u) rescue nil }
      chat_channels << ch
    rescue => e
      warn "chat dm channel failed: #{e.class} #{e.message}"
      break if Chat::DirectMessageChannel.count > 0
    end
  end
  chat_channels += Chat::Channel.limit(50).to_a
  chat_channels.uniq!

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
  target_messages = 1500
  while Chat::Message.count < target_messages
    ch = chat_channels.sample
    user = users.sample
    begin
      ch.add(user) rescue nil
      created_at = rand(180).days.ago
      m = Chat::Message.new(
        chat_channel: ch,
        user: user,
        last_editor_id: user.id,
        message: "#{chat_phrases.sample} Synthetic chat about #{nouns.sample} #{SecureRandom.hex(2)}.",
        created_at: created_at,
        updated_at: created_at
      )
      m.cook if m.respond_to?(:cook)
      m.save!
      chat_messages_created += 1
      if rand < 0.30 && defined?(Chat::MessageReaction)
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
  Chat::Channel.find_each do |ch|
    last = ch.chat_messages.order(:created_at).last
    ch.update_columns(
      chat_messages_count: ch.chat_messages.count,
      user_count: ch.user_chat_channel_memberships.count,
      last_message_id: last&.id,
      last_message_created_at: last&.created_at
    ) rescue nil
  end
end
puts "chat_channels=#{defined?(Chat::Channel) ? Chat::Channel.count : 0}"
puts "chat_messages=#{defined?(Chat::Message) ? Chat::Message.count : 0} created=#{chat_messages_created}"
puts "chat_message_reactions=#{defined?(Chat::MessageReaction) ? Chat::MessageReaction.count : 0}"

Topic.find_each do |t|
  begin
    t.update_columns(
      posts_count: Post.where(topic_id: t.id, deleted_at: nil).count,
      like_count: Post.where(topic_id: t.id).sum(:like_count)
    )
  rescue
    nil
  end
end

summary = {
  users: User.real.count,
  categories: Category.count,
  tags: defined?(Tag) ? Tag.count : 0,
  topics: Topic.count,
  posts: Post.count,
  private_messages: Topic.where(archetype: Archetype.private_message).count,
  post_actions: PostAction.count,
  likes: PostAction.where(post_action_type_id: PostActionType::LIKE_POST_ACTION_ID).count,
  reaction_users: (defined?(DiscourseReactions::ReactionUser) ? DiscourseReactions::ReactionUser.count : 0),
  chat_channels: (defined?(Chat::Channel) ? Chat::Channel.count : 0),
  chat_messages: (defined?(Chat::Message) ? Chat::Message.count : 0),
  chat_message_reactions: (defined?(Chat::MessageReaction) ? Chat::MessageReaction.count : 0),
}
puts "RECOVERY_ENRICH_SUMMARY=#{summary.to_json}"
