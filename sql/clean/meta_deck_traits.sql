-- 메타 덱 보드의 시너지 → 시너지 한 행. style 0은 비활성 (docs/DATA_SOURCES.md).
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
  board.stage,
  JSON_VALUE(t, '$.key') AS trait_id,
  LAX_INT64(t.style) AS style,
  LAX_INT64(t.numUnits) AS num_units
FROM deck,
  UNNEST([
    STRUCT('final' AS stage, deck.d AS s),
    STRUCT('early' AS stage, deck.d.early AS s),
    STRUCT('middle' AS stage, deck.d.middle AS s)
  ]) AS board,
  UNNEST(JSON_QUERY_ARRAY(board.s, '$.traits')) AS t
