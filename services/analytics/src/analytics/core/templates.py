TEMPLATES = {
    "overview_stats": """
        SELECT
            countIf(event_name IN ('view', 'video_view')) as views,
            sumIf(toInt64OrZero(JSONExtractString(properties, 'watch_time')), event_name = 'video_heartbeat') / 3600 as watch_time_hours,
            countIf(event_name = 'channel_subscribe') - countIf(event_name = 'channel_unsubscribe') as subscriber_change,
            if(countIf(event_name IN ('view', 'video_view')) > 0, sumIf(toInt64OrZero(JSONExtractString(properties, 'watch_time')), event_name = 'video_heartbeat') / countIf(event_name IN ('view', 'video_view')), 0) as avg_view_duration
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND timestamp >= now() - INTERVAL {days:Int32} DAY
          AND JSONExtractString(properties, 'channel_id') = {channel_id:String}
    """,
    "chronological_trend": """
        SELECT
            toStartOfInterval(timestamp, if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1))) as bucket,
            countIf(event_name IN ('view', 'video_view')) as views
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND timestamp >= now() - INTERVAL {days:Int32} DAY
          AND JSONExtractString(properties, 'channel_id') = {channel_id:String}
        GROUP BY bucket
        ORDER BY bucket ASC WITH FILL 
            FROM toStartOfInterval(now() - INTERVAL {days:Int32} DAY, if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1)))
            TO toStartOfInterval(now(), if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1)))
            STEP if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1))
    """,
    "top_content": """
        SELECT
            JSONExtractString(properties, 'video_id') as video_id,
            any(JSONExtractString(properties, 'title')) as title,
            any(JSONExtractString(properties, 'thumbnail_url')) as thumbnail_url,
            countIf(event_name IN ('view', 'video_view')) as views,
            if(countIf(event_name IN ('view', 'video_view')) > 0, sumIf(toInt64OrZero(JSONExtractString(properties, 'watch_time')), event_name = 'video_heartbeat') / countIf(event_name IN ('view', 'video_view')), 0) as avg_view_duration
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND event_name IN ('view', 'video_view', 'video_heartbeat')
          AND timestamp >= now() - INTERVAL {days:Int32} DAY
          AND JSONExtractString(properties, 'video_id') != ''
          AND JSONExtractString(properties, 'channel_id') = {channel_id:String}
        GROUP BY video_id
        ORDER BY views DESC
        LIMIT {limit:Int32}
    """,
    "realtime_stats": """
        SELECT
            (SELECT count(DISTINCT user_id) FROM octane_events WHERE app_id = {app_id:String} AND event_name = 'video_heartbeat' AND JSONExtractString(properties, 'channel_id') = {channel_id:String} AND timestamp >= now() - INTERVAL 5 MINUTE) as active_viewers,
            (SELECT count() FROM octane_events WHERE app_id = {app_id:String} AND event_name IN ('view', 'video_view') AND JSONExtractString(properties, 'channel_id') = {channel_id:String} AND timestamp >= now() - INTERVAL 48 HOUR) as views_48h
    """,
    "realtime_velocity": """
        SELECT
            toStartOfHour(timestamp) as hour,
            count() as views
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND event_name IN ('view', 'video_view')
          AND timestamp >= now() - INTERVAL 48 HOUR
          AND JSONExtractString(properties, 'channel_id') = {channel_id:String}
        GROUP BY hour
        ORDER BY hour ASC WITH FILL 
            FROM toStartOfHour(now() - INTERVAL 48 HOUR)
            TO toStartOfHour(now() + INTERVAL 1 HOUR)
            STEP toIntervalHour(1)
    """,
    "search_analytics": """
        SELECT
            JSONExtractString(properties, 'query') as query,
            count() as count
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND event_name IN ('search', 'search_query')
          AND timestamp >= now() - INTERVAL {days:Int32} DAY
          AND JSONExtractString(properties, 'query') != ''
        GROUP BY query
        ORDER BY count DESC
        LIMIT {limit:Int32}
    """,
    "engagement_trend": """
        SELECT
            toStartOfInterval(timestamp, if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1))) as bucket,
            countIf(event_name IN ('comment', 'comment_add', 'chat_message')) as comments,
            countIf(event_name IN ('like', 'video_like')) as likes,
            countIf(event_name IN ('share', 'video_share', 'video_share_click')) as shares
        FROM octane_events
        WHERE app_id = {app_id:String}
          AND timestamp >= now() - INTERVAL {days:Int32} DAY
          AND JSONExtractString(properties, 'channel_id') = {channel_id:String}
        GROUP BY bucket
        ORDER BY bucket ASC WITH FILL 
            FROM toStartOfInterval(now() - INTERVAL {days:Int32} DAY, if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1)))
            TO toStartOfInterval(now(), if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1)))
            STEP if({days:Int32} >= 7, toIntervalDay(1), toIntervalHour(1))
    """
}
def get_query(name: str, params: dict) -> str:
    if name not in TEMPLATES:
        raise ValueError(f"Template '{name}' not found")
    return TEMPLATES[name]
