-- 상징 → 장착 챔피언 → 그 챔피언이 최종 보드에 있는 메타 덱. 상징 → 덱 직접 통계가 없어서 만드는 근사.
-- 장착 챔피언이 어느 메타 덱에도 없으면 덱 칼럼은 NULL.
-- next_breakpoint_reached: 덱의 그 시너지 유닛 수 + 1이 시너지 단계 중 하나와 같은가.
--   시너지 단계 정보가 없으면(예: 일월식) NULL.
-- ID는 static_id_map으로만 잇는다. 시너지 키는 OP.GG와 CDragon이 같은 apiName이다.
-- 매개변수: @snapshot_date, @set_number
WITH emblems AS (
  SELECT
    m.opgg_id AS emblem_id,
    i.emblem_trait
  FROM static_id_map AS m
  JOIN static_items AS i
    ON i.api_name = m.api_name
  WHERE m.type = 'item'
    AND i.kind = 'emblem'
    AND i.set_number = @set_number
),

holders AS (
  SELECT
    e.emblem_id,
    e.emblem_trait,
    h.unit_id,
    h.n AS holder_n,
    h.avg_place AS holder_avg_place,
    h.source_updated_at
  FROM item_holders AS h
  JOIN emblems AS e
    ON e.emblem_id = h.item_id
  WHERE h.snapshot_date = @snapshot_date
),

deck_units AS (
  SELECT DISTINCT deck_id, unit_id
  FROM meta_deck_units
  WHERE snapshot_date = @snapshot_date
    AND stage = 'final'
),

decks AS (
  SELECT deck_id, name_ko, avg_place
  FROM meta_decks
  WHERE snapshot_date = @snapshot_date
),

final_traits AS (
  SELECT deck_id, trait_id, num_units
  FROM meta_deck_traits
  WHERE snapshot_date = @snapshot_date
    AND stage = 'final'
),

traits AS (
  SELECT api_name, breakpoints
  FROM static_traits
  WHERE set_number = @set_number
)

SELECT
  @snapshot_date AS snapshot_date,
  h.source_updated_at,
  h.emblem_id,
  h.emblem_trait,
  h.unit_id,
  h.holder_n,
  h.holder_avg_place,
  d.deck_id,
  d.name_ko AS deck_name_ko,
  d.avg_place AS deck_avg_place,
  IF(d.deck_id IS NULL, NULL, COALESCE(ft.num_units, 0)) AS trait_count_in_deck,
  CASE
    WHEN d.deck_id IS NULL OR t.breakpoints IS NULL OR ARRAY_LENGTH(t.breakpoints) = 0 THEN NULL
    ELSE COALESCE(ft.num_units, 0) + 1 IN UNNEST(t.breakpoints)
  END AS next_breakpoint_reached
FROM holders AS h
LEFT JOIN deck_units AS du
  ON du.unit_id = h.unit_id
LEFT JOIN decks AS d
  ON d.deck_id = du.deck_id
LEFT JOIN final_traits AS ft
  ON ft.deck_id = d.deck_id
  AND ft.trait_id = h.emblem_trait
LEFT JOIN traits AS t
  ON t.api_name = h.emblem_trait
