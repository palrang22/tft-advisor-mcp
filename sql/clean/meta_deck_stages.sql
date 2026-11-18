-- 메타 덱의 레벨5(early)·레벨7(middle) 보드 판수. win·lose의 정의는 미확인이라 원래 숫자 그대로 둔다.
-- 여러 최종 덱이 같은 stage_deck_id를 공유하면 판수도 같다 (보드 기준 통계).
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
  JSON_VALUE(board.s, '$.deckId') AS stage_deck_id,
  LAX_INT64(board.s.level) AS level,
  LAX_INT64(board.s.play) AS play,
  LAX_INT64(board.s.win) AS win,
  LAX_INT64(board.s.lose) AS lose
FROM deck,
  UNNEST([
    STRUCT('early' AS stage, deck.d.early AS s),
    STRUCT('middle' AS stage, deck.d.middle AS s)
  ]) AS board
WHERE board.s IS NOT NULL
