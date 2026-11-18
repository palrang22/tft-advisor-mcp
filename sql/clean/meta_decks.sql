-- 메타 덱 응답 → 덱 한 행.
-- 매개변수: @snapshot_date
WITH deck AS (
  SELECT
    r.snapshot_date,
    r.source_updated_at,
    d
  FROM raw_opgg AS r,
    UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(r.payload, wide_number_mode => 'round'), '$.data')) AS d
  WHERE r.snapshot_date = @snapshot_date
    AND r.tool = 'tft_list_meta_decks'
    AND r.status = 'ok'
)

SELECT
  snapshot_date,
  source_updated_at,
  JSON_VALUE(d, '$.id') AS deck_id,
  JSON_VALUE(d, '$.name.ko_KR') AS name_ko,
  JSON_VALUE(d, '$.teamCode') AS team_code,
  JSON_VALUE(d, '$.stat.opTier') AS op_tier,
  LAX_FLOAT64(d.stat.opScore) AS op_score,
  LAX_INT64(d.stat.labelNumber) AS label_number,
  LAX_INT64(d.stat.deck.compsCount) AS n,
  LAX_FLOAT64(d.stat.deck.avgPlacement) AS avg_place,
  LAX_FLOAT64(d.stat.deck.top4Rate) AS top4_rate,
  LAX_FLOAT64(d.stat.deck.winRate) AS win_rate,
  LAX_FLOAT64(d.stat.deck.pickRate) AS pick_rate,
  LAX_INT64(d.stat.label.compsCount) AS label_n,
  LAX_FLOAT64(d.stat.label.avgPlacement) AS label_avg_place,
  LAX_FLOAT64(d.stat.label.top4Rate) AS label_top4_rate,
  -- badge는 빈 배열인 날이 있다 (2026-11-13은 전부 빈 배열). 없으면 NULL.
  (
    SELECT LAX_INT64(b.value)
    FROM UNNEST(JSON_QUERY_ARRAY(d, '$.badge')) AS b
    WHERE JSON_VALUE(b, '$.key') = 'difficulty'
    LIMIT 1
  ) AS difficulty,
  (
    SELECT LAX_INT64(b.value)
    FROM UNNEST(JSON_QUERY_ARRAY(d, '$.badge')) AS b
    WHERE JSON_VALUE(b, '$.key') = 'reroll'
    LIMIT 1
  ) AS reroll_level,
  (
    SELECT LAX_INT64(b.value)
    FROM UNNEST(JSON_QUERY_ARRAY(d, '$.badge')) AS b
    WHERE JSON_VALUE(b, '$.key') = 'tempo'
    LIMIT 1
  ) AS tempo,
  (
    SELECT JSON_VALUE(b, '$.value')
    FROM UNNEST(JSON_QUERY_ARRAY(d, '$.badge')) AS b
    WHERE JSON_VALUE(b, '$.key') = 'ppm'
    LIMIT 1
  ) AS ppm
FROM deck
