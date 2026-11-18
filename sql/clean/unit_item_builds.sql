-- 챔피언 빌드 응답 → 3템 조합 한 행. 응답은 {"data": [...]} 또는 최상위 배열 둘 다 처리한다.
-- 통계가 없는 챔피언은 {"data": []}라 행이 생기지 않는다.
-- 매개변수: @snapshot_date
WITH response AS (
  SELECT
    r.snapshot_date,
    r.source_updated_at,
    PARSE_JSON(r.payload, wide_number_mode => 'round') AS j
  FROM raw_opgg AS r
  WHERE r.snapshot_date = @snapshot_date
    AND r.tool = 'tft_get_champion_item_build'
    AND r.status = 'ok'
)

SELECT
  response.snapshot_date,
  response.source_updated_at,
  JSON_VALUE(b, '$.characterId') AS unit_id,
  ARRAY(
    SELECT JSON_VALUE(i)
    FROM UNNEST(JSON_QUERY_ARRAY(b, '$.itemNames')) AS i
    ORDER BY JSON_VALUE(i)
  ) AS items,
  LAX_INT64(b.itemCount) AS n,
  LAX_INT64(b.totalChampionCount) AS unit_total,
  LAX_FLOAT64(b.avgPlacement) AS avg_place,
  LAX_FLOAT64(b.top4Rate) AS top4_rate,
  LAX_FLOAT64(b.winRate) AS win_rate
FROM response,
  UNNEST(COALESCE(JSON_QUERY_ARRAY(response.j, '$.data'), JSON_QUERY_ARRAY(response.j, '$'))) AS b
