-- 템별 챔피언 응답 → (템, 장착 챔피언) 한 행. item_id는 호출 인자.
-- 응답은 최상위 배열 또는 {"data": [...]} 둘 다 처리한다.
-- 매개변수: @snapshot_date
WITH response AS (
  SELECT
    r.snapshot_date,
    r.source_updated_at,
    JSON_VALUE(r.args, '$.item_id') AS item_id,
    PARSE_JSON(r.payload, wide_number_mode => 'round') AS j
  FROM raw_opgg AS r
  WHERE r.snapshot_date = @snapshot_date
    AND r.tool = 'tft_list_champions_for_item'
    AND r.status = 'ok'
)

SELECT
  response.snapshot_date,
  response.source_updated_at,
  response.item_id,
  JSON_VALUE(h, '$.characterId') AS unit_id,
  LAX_INT64(h.totalCount) AS n,
  LAX_FLOAT64(h.avgPlacement) AS avg_place,
  LAX_FLOAT64(h.top4Rate) AS top4_rate,
  LAX_FLOAT64(h.winRate) AS win_rate
FROM response,
  UNNEST(COALESCE(JSON_QUERY_ARRAY(response.j, '$.data'), JSON_QUERY_ARRAY(response.j, '$'))) AS h
