-- Where in the funnel does the gate position matter?
-- Players are bucketed by rounds played in their first 14 days; the gate sits at level 30 or 40,
-- so only players who get that far can actually experience the difference.
WITH bucketed AS (
    SELECT
        version,
        retention_7,
        CASE
            WHEN sum_gamerounds = 0   THEN '0 rounds'
            WHEN sum_gamerounds < 30  THEN '1-29 (before either gate)'
            WHEN sum_gamerounds < 40  THEN '30-39 (between gates)'
            WHEN sum_gamerounds < 100 THEN '40-99'
            ELSE '100+'
        END AS engagement_bucket,
        CASE
            WHEN sum_gamerounds = 0   THEN 1
            WHEN sum_gamerounds < 30  THEN 2
            WHEN sum_gamerounds < 40  THEN 3
            WHEN sum_gamerounds < 100 THEN 4
            ELSE 5
        END AS bucket_order
    FROM players
)
SELECT
    engagement_bucket,
    bucket_order,
    version,
    COUNT(*)                            AS players,
    AVG(CAST(retention_7 AS DOUBLE))    AS d7_rate
FROM bucketed
GROUP BY engagement_bucket, bucket_order, version
ORDER BY bucket_order, version;
