-- Self page schema: habits and checkins
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS habits (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS checkins (
    id         SERIAL PRIMARY KEY,
    habit_id   TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    date       DATE NOT NULL DEFAULT CURRENT_DATE,
    done       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(habit_id, date)
);

CREATE INDEX IF NOT EXISTS idx_checkins_habit_date ON checkins(habit_id, date);
CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(date);
