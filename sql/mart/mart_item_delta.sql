-- 챔피언별 템 착용 효과. 3템 조합 통계에서 "이 템이 든 조합"과 "안 든 조합"의 판수 가중 평균 등수 차이.
-- delta = avg_with - avg_without. 음수면 등수를 올려 주는 템.
-- 한계: 3템을 모두 든 판끼리 비교한 값이다 (OP.GG가 3템 조합만 준다).
-- 같은 템이 두 번 든 조합은 그 템을 한 번만 센다.
-- 매개변수: @snapshot_date, @low_sample_n
WITH builds AS (
  SELECT unit_id, items, n, avg_place, source_updated_at
  FROM unit_item_builds
  WHERE snapshot_date = @snapshot_date
),

unit_all AS (
  SELECT
    unit_id,
    SUM(n) AS n_all,
    SUM(n * avg_place) AS place_sum_all
  FROM builds
  GROUP BY unit_id
),

with_item AS (
  SELECT
    b.unit_id,
    item_id,
    SUM(b.n) AS n_with,
    SUM(b.n * b.avg_place) AS place_sum_with,
    ANY_VALUE(b.source_updated_at) AS source_updated_at
  FROM builds AS b,
    UNNEST(ARRAY(SELECT DISTINCT x FROM UNNEST(b.items) AS x)) AS item_id
  GROUP BY b.unit_id, item_id
),

joined AS (
  SELECT
    w.unit_id,
    w.item_id,
    w.source_updated_at,
    w.n_with,
    w.place_sum_with / w.n_with AS avg_with,
    a.n_all - w.n_with AS n_without,
    SAFE_DIVIDE(a.place_sum_all - w.place_sum_with, a.n_all - w.n_with) AS avg_without
  FROM with_item AS w
  JOIN unit_all AS a USING (unit_id)
)

SELECT
  @snapshot_date AS snapshot_date,
  source_updated_at,
  unit_id,
  item_id,
  n_with,
  avg_with,
  n_without,
  avg_without,
  avg_with - avg_without AS delta,
  n_with < @low_sample_n AS low_sample
FROM joined
