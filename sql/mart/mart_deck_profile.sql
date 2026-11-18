-- deck_detail이 한 번에 읽도록 덱 단위로 묶은 표: 덱 통계, 최종 보드, 시너지, 레벨5·7 보드와 판수.
-- 최종 보드는 우선순위(1이 최우선) → 나머지 순. 시너지는 활성(style 큰 순) → 인원 순.
-- 매개변수: @snapshot_date
WITH units AS (
  SELECT *
  FROM meta_deck_units
  WHERE snapshot_date = @snapshot_date
),

traits AS (
  SELECT *
  FROM meta_deck_traits
  WHERE snapshot_date = @snapshot_date
),

final_units AS (
  SELECT
    deck_id,
    ARRAY_AGG(
      STRUCT(unit_id, star, items, is_core, priority, cell_x, cell_y)
      ORDER BY priority IS NULL, priority, unit_id
    ) AS units
  FROM units
  WHERE stage = 'final'
  GROUP BY deck_id
),

stage_units AS (
  SELECT
    deck_id,
    stage,
    ARRAY_AGG(STRUCT(unit_id, cell_x, cell_y) ORDER BY unit_id) AS units
  FROM units
  WHERE stage IN ('early', 'middle')
  GROUP BY deck_id, stage
),

stage_traits AS (
  SELECT
    deck_id,
    stage,
    ARRAY_AGG(STRUCT(trait_id, style, num_units) ORDER BY style DESC, num_units DESC, trait_id)
      AS traits
  FROM traits
  GROUP BY deck_id, stage
),

boards AS (
  SELECT
    s.deck_id,
    s.stage,
    STRUCT(
      s.stage_deck_id,
      s.level,
      s.play,
      s.win,
      s.lose,
      su.units,
      st.traits
    ) AS board
  FROM meta_deck_stages AS s
  LEFT JOIN stage_units AS su
    ON su.deck_id = s.deck_id
    AND su.stage = s.stage
  LEFT JOIN stage_traits AS st
    ON st.deck_id = s.deck_id
    AND st.stage = s.stage
  WHERE s.snapshot_date = @snapshot_date
)

SELECT
  d.snapshot_date,
  d.source_updated_at,
  d.deck_id,
  d.name_ko,
  d.team_code,
  d.op_tier,
  d.op_score,
  d.label_number,
  d.n,
  d.avg_place,
  d.top4_rate,
  d.win_rate,
  d.pick_rate,
  d.label_n,
  d.label_avg_place,
  d.label_top4_rate,
  d.difficulty,
  d.reroll_level,
  d.tempo,
  d.ppm,
  fu.units AS final_units,
  ft.traits AS final_traits,
  early.board AS early,
  middle.board AS middle
FROM meta_decks AS d
LEFT JOIN final_units AS fu
  ON fu.deck_id = d.deck_id
LEFT JOIN stage_traits AS ft
  ON ft.deck_id = d.deck_id
  AND ft.stage = 'final'
LEFT JOIN boards AS early
  ON early.deck_id = d.deck_id
  AND early.stage = 'early'
LEFT JOIN boards AS middle
  ON middle.deck_id = d.deck_id
  AND middle.stage = 'middle'
WHERE d.snapshot_date = @snapshot_date
