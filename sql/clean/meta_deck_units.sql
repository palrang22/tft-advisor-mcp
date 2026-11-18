-- 메타 덱 보드 → 유닛 한 행. 최종(final)·레벨5(early)·레벨7(middle) 보드를 stage로 구분한다.
-- early·middle의 items는 응답에서 항상 [null, null, null]이라 빈 배열로 둔다.
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
  deck.snapshot_date,
  deck.source_updated_at,
  JSON_VALUE(deck.d, '$.id') AS deck_id,
  'final' AS stage,
  JSON_VALUE(deck.d, '$.id') AS stage_deck_id,
  CAST(NULL AS INT64) AS level,
  JSON_VALUE(u, '$.key') AS unit_id,
  LAX_INT64(u.tier) AS star,
  ARRAY(
    SELECT JSON_VALUE(i)
    FROM UNNEST(JSON_QUERY_ARRAY(u, '$.items')) AS i
    WHERE JSON_VALUE(i) IS NOT NULL
  ) AS items,
  LAX_BOOL(u.isCore) AS is_core,
  LAX_INT64(u.priority) AS priority,
  LAX_INT64(u.cell.x) AS cell_x,
  LAX_INT64(u.cell.y) AS cell_y
FROM deck,
  UNNEST(JSON_QUERY_ARRAY(deck.d, '$.units')) AS u

UNION ALL

SELECT
  deck.snapshot_date,
  deck.source_updated_at,
  JSON_VALUE(deck.d, '$.id') AS deck_id,
  board.stage,
  JSON_VALUE(board.s, '$.deckId') AS stage_deck_id,
  LAX_INT64(board.s.level) AS level,
  JSON_VALUE(u, '$.characterId') AS unit_id,
  CAST(NULL AS INT64) AS star,
  CAST([] AS ARRAY<STRING>) AS items,
  CAST(NULL AS BOOL) AS is_core,
  CAST(NULL AS INT64) AS priority,
  LAX_INT64(u.cell.x) AS cell_x,
  LAX_INT64(u.cell.y) AS cell_y
FROM deck,
  UNNEST([
    STRUCT('early' AS stage, deck.d.early AS s),
    STRUCT('middle' AS stage, deck.d.middle AS s)
  ]) AS board,
  UNNEST(JSON_QUERY_ARRAY(board.s, '$.units')) AS u
