-- 메타 덱 캐리 템을 재료로 분해한 수요. 최종 보드의 핵심 유닛(is_core) 템만 센다.
-- 템 ID는 static_id_map → static_items.components로 분해한다. 재료 템은 그 자체로 센다.
-- 조합식이 없는 템(유물, 조합식 없는 상징 등)과 매핑되지 않는 템은 수요에 들어가지 않는다.
-- component_id는 CDragon apiName (Set 18은 OP.GG ID와 같다).
-- 매개변수: @snapshot_date, @set_number
WITH core_items AS (
  SELECT
    u.deck_id,
    u.source_updated_at,
    item_id
  FROM meta_deck_units AS u,
    UNNEST(u.items) AS item_id
  WHERE u.snapshot_date = @snapshot_date
    AND u.stage = 'final'
    AND u.is_core
),

items AS (
  SELECT
    m.opgg_id,
    i.api_name,
    i.kind,
    i.components
  FROM static_id_map AS m
  JOIN static_items AS i
    ON i.api_name = m.api_name
  WHERE m.type = 'item'
    AND i.set_number = @set_number
)

SELECT
  @snapshot_date AS snapshot_date,
  ANY_VALUE(c.source_updated_at) AS source_updated_at,
  c.deck_id,
  component_id,
  COUNT(*) AS count
FROM core_items AS c
JOIN items AS i
  ON i.opgg_id = c.item_id
CROSS JOIN UNNEST(IF(i.kind = 'component', [i.api_name], i.components)) AS component_id
GROUP BY c.deck_id, component_id
