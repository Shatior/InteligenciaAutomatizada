-- Esquema idempotente: se ejecuta en cada arranque.

CREATE TABLE IF NOT EXISTS fuentes (
    id                  TEXT PRIMARY KEY,
    nombre              TEXT NOT NULL,
    url                 TEXT NOT NULL,
    metodo              TEXT NOT NULL DEFAULT 'rss',      -- rss | html
    dominio             TEXT NOT NULL,                     -- geopolitica | ciber | transformacion | macro
    region              TEXT NOT NULL DEFAULT 'global',    -- global | latam | centroamerica
    idioma              TEXT NOT NULL DEFAULT 'en',
    tipo                TEXT NOT NULL DEFAULT 'prensa',    -- oficial | think_tank | prensa | especializado
    fiabilidad          TEXT NOT NULL DEFAULT 'C',         -- escala Admiralty A-F
    activa              BOOLEAN NOT NULL DEFAULT TRUE,
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    ultimo_intento      TIMESTAMPTZ,
    ultimo_ok           TIMESTAMPTZ,
    ultimo_error        TEXT,
    fallos_consecutivos INT NOT NULL DEFAULT 0,
    items_ultimo        INT NOT NULL DEFAULT 0,
    items_total         INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    id                  BIGSERIAL PRIMARY KEY,
    fuente_id           TEXT NOT NULL REFERENCES fuentes(id),
    url                 TEXT NOT NULL,
    url_hash            TEXT NOT NULL UNIQUE,
    titulo              TEXT,
    titulo_hash         TEXT,
    publicado           TIMESTAMPTZ,
    recolectado         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resumen_fuente      TEXT,
    texto               TEXT,
    texto_metodo        TEXT,          -- feed | http | navegador | sigilo | pdf
    texto_error         TEXT,
    estado              TEXT NOT NULL DEFAULT 'nuevo',  -- nuevo | con_texto | sin_texto | duplicado | puntuado
    -- puntuación
    dominio             TEXT,
    linea               TEXT,
    regiones            TEXT[],
    paises              TEXT[],
    entidades           TEXT[],
    magnitud            SMALLINT,
    novedad             SMALLINT,
    datos               SMALLINT,
    relevancia_ca       SMALLINT,
    cruce               BOOLEAN,
    tecnico             BOOLEAN,
    resumen             TEXT,
    puntuacion_global   REAL,
    puntuacion_regional REAL,
    puntuado_en         TIMESTAMPTZ,
    tsv                 TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple'::regconfig,
            coalesce(titulo, '') || ' ' || coalesce(resumen, '') || ' ' || left(coalesce(texto, ''), 100000))
    ) STORED
);
CREATE INDEX IF NOT EXISTS items_tsv_idx ON items USING GIN (tsv);
CREATE INDEX IF NOT EXISTS items_estado_idx ON items (estado);
CREATE INDEX IF NOT EXISTS items_recolectado_idx ON items (recolectado DESC);
CREATE INDEX IF NOT EXISTS items_titulo_hash_idx ON items (titulo_hash);
CREATE INDEX IF NOT EXISTS items_dominio_idx ON items (dominio, recolectado DESC);

CREATE TABLE IF NOT EXISTS candidatos (
    id              BIGSERIAL PRIMARY KEY,
    semana          DATE NOT NULL,           -- lunes de la semana ISO
    edicion         TEXT NOT NULL,
    titulo          TEXT NOT NULL,
    etiqueta        TEXT,
    hecho           TEXT,
    por_que         TEXT,
    tesis           JSONB NOT NULL DEFAULT '[]'::jsonb,
    item_ids        BIGINT[] NOT NULL DEFAULT '{}',
    puntuacion      REAL,
    estado          TEXT NOT NULL DEFAULT 'propuesto',  -- propuesto | elegido | descartado
    creado          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS candidatos_semana_idx ON candidatos (semana DESC, edicion);

CREATE TABLE IF NOT EXISTS dossieres (
    id               BIGSERIAL PRIMARY KEY,
    candidato_id     BIGINT REFERENCES candidatos(id) ON DELETE SET NULL,
    edicion          TEXT NOT NULL,
    tema             TEXT NOT NULL,
    enfoque          TEXT,
    estado           TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | en_curso | listo | error
    error            TEXT,
    consultas        JSONB NOT NULL DEFAULT '[]'::jsonb,
    hechos           JSONB NOT NULL DEFAULT '[]'::jsonb,
    voces            JSONB NOT NULL DEFAULT '[]'::jsonb,
    contexto         JSONB NOT NULL DEFAULT '[]'::jsonb,
    contraargumentos JSONB NOT NULL DEFAULT '[]'::jsonb,
    lagunas          JSONB NOT NULL DEFAULT '[]'::jsonb,
    tesis            JSONB NOT NULL DEFAULT '[]'::jsonb,
    creado           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dossier_fuentes (
    id          BIGSERIAL PRIMARY KEY,
    dossier_id  BIGINT NOT NULL REFERENCES dossieres(id) ON DELETE CASCADE,
    n           INT NOT NULL,             -- número de fuente dentro del dossier
    url         TEXT NOT NULL,
    titulo      TEXT,
    medio       TEXT,
    publicado   TIMESTAMPTZ,
    origen      TEXT NOT NULL,            -- radar | archivo | busqueda
    fiabilidad  TEXT,
    texto       TEXT
);
CREATE INDEX IF NOT EXISTS dossier_fuentes_idx ON dossier_fuentes (dossier_id, n);

CREATE TABLE IF NOT EXISTS piezas (
    id           BIGSERIAL PRIMARY KEY,
    dossier_id   BIGINT NOT NULL REFERENCES dossieres(id) ON DELETE CASCADE,
    edicion      TEXT NOT NULL,
    tesis        TEXT,
    etiqueta     TEXT,
    titulo       TEXT,
    entradilla   TEXT,
    cuerpo       TEXT,
    palabras     INT,
    verificacion JSONB NOT NULL DEFAULT '{}'::jsonb,
    estado       TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | borrador | editada | aprobada | error
    error        TEXT,
    creado       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trabajos (
    id        BIGSERIAL PRIMARY KEY,
    tipo      TEXT NOT NULL,              -- radar | candidatos | dossier | pieza
    payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    estado    TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | en_curso | hecho | error
    origen    TEXT NOT NULL DEFAULT 'panel',      -- panel | programado | arranque
    error     TEXT,
    resultado JSONB,
    creado    TIMESTAMPTZ NOT NULL DEFAULT now(),
    iniciado  TIMESTAMPTZ,
    terminado TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS trabajos_estado_idx ON trabajos (estado, creado);

CREATE TABLE IF NOT EXISTS uso_llm (
    id        BIGSERIAL PRIMARY KEY,
    momento   TIMESTAMPTZ NOT NULL DEFAULT now(),
    etapa     TEXT NOT NULL,
    modelo    TEXT NOT NULL,
    entrada   INT NOT NULL DEFAULT 0,
    salida    INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS uso_llm_momento_idx ON uso_llm (momento DESC);
