-- Per-variant sample sizes and outcome rates: the inputs to every test.
SELECT
    version,
    COUNT(*)                                              AS players,
    SUM(CAST(retention_1 AS INTEGER))                     AS retained_d1,
    SUM(CAST(retention_7 AS INTEGER))                     AS retained_d7,
    AVG(CAST(retention_1 AS DOUBLE))                      AS d1_rate,
    AVG(CAST(retention_7 AS DOUBLE))                      AS d7_rate,
    AVG(sum_gamerounds)                                   AS mean_rounds,
    MEDIAN(sum_gamerounds)                                AS median_rounds,
    AVG(CASE WHEN sum_gamerounds = 0 THEN 1.0 ELSE 0 END) AS share_never_played
FROM players
GROUP BY version
ORDER BY version;
