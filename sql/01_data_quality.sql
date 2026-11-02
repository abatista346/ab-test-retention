-- Data quality checks run before any statistics.
-- Every row must be one player; flags must be boolean; engagement must be non-negative.
SELECT
    COUNT(*)                                             AS n_rows,
    COUNT(DISTINCT userid)                               AS n_unique_players,
    COUNT(*) - COUNT(DISTINCT userid)                    AS n_duplicate_rows,
    SUM(CASE WHEN version NOT IN ('gate_30', 'gate_40') THEN 1 ELSE 0 END) AS n_unknown_variant,
    SUM(CASE WHEN sum_gamerounds IS NULL OR sum_gamerounds < 0 THEN 1 ELSE 0 END) AS n_invalid_rounds,
    SUM(CASE WHEN retention_1 IS NULL OR retention_7 IS NULL THEN 1 ELSE 0 END) AS n_missing_retention,
    MAX(sum_gamerounds)                                  AS max_rounds,
    QUANTILE_CONT(sum_gamerounds, 0.99)                  AS p99_rounds
FROM players;
