# InteligenciaAutomatizada

Sistema de inteligencia para producir piezas semanales de análisis en tres dominios:
geopolítica (edición global y edición Centroamérica/Latinoamérica), ciberriesgo estratégico
y transformación digital financiera.

El sistema recoge y ordena; el criterio editorial es de quien lo usa. Propone temas y tesis,
monta el dossier con cada dato trazado a su fuente, redacta un borrador y señala lo que no
puede respaldar. La elección del tema, la tesis y la aprobación son decisiones humanas.

## Cómo funciona

```
config/fuentes.yaml ──► RADAR (cada 6 h) ──► archivo en Postgres ──► CANDIDATOS (jueves)
                         RSS · HTML · PDF      texto completo           8-10 temas por edición
                         Scrapling por niveles puntuación con Claude    con 2-3 tesis cada uno
                                                                              │ eliges en el panel
                                                                              ▼
                        PIEZA ◄── tesis elegida ◄── DOSSIER (a demanda)
                        borrador 700-900 palabras    búsqueda con Exa + archivo propio
                        verificación de cifras       hechos con cita literal comprobada
```

| Etapa | Qué hace | Con qué |
|---|---|---|
| Radar | Lee las fuentes del registro, trae el texto completo, deduplica y puntúa | feedparser, Scrapling, trafilatura, PyMuPDF, Claude (modelo rápido) |
| Candidatos | Agrupa lo mejor de la semana en temas con tesis posibles, por edición | Claude |
| Dossier | Busca 15-20 fuentes sobre el tema y extrae hechos, voces y contraargumentos | Exa, Scrapling, Claude |
| Pieza | Redacta según `config/guia_pieza.md` y audita el borrador contra el dossier | Claude |

### Dos notas por item

Cada item recibe una **nota global** (magnitud, novedad, riqueza de datos) y una **nota regional**
(efecto sobre Centroamérica, ocurra donde ocurra el hecho). La edición global ordena por la primera;
las demás, por la segunda.

### Salvaguardas contra datos inventados

1. Un candidato solo se guarda si apunta a items reales del radar.
2. Cada hecho del dossier lleva una cita literal; un programa comprueba que esa cita aparece en el
   texto de la fuente. Lo que no se localiza queda como «no verificado» y no se usa al redactar.
3. Tras redactar, se cotejan todas las cifras del borrador contra el dossier y un segundo paso del
   modelo busca afirmaciones sin respaldo. El panel muestra ambas listas junto al texto.

Ninguna de las tres sustituye la lectura del editor.

## Obtención por niveles (Scrapling)

| Nivel | Cuándo | Activación |
|---|---|---|
| HTTP con huella de navegador | Siempre | Por defecto |
| Chromium | Páginas que se pintan con JavaScript | `navegador: true` en la fuente; siempre disponible para el dossier |
| Navegador sigiloso (resuelve Cloudflare) | Fuentes que bloquean | Solo con `sigilo: true` en la fuente |

El nivel sigiloso es una decisión por fuente: saltarse una protección anti-bot puede ir contra los
términos de uso del sitio. Las fuentes de pago se marcan `solo_feed: true` y no se trae su artículo.

## Servicios en Railway

| Servicio | Orden | Función |
|---|---|---|
| `Postgres` | — | Archivo, cola de trabajos, registro de consumo |
| `motor` | `python -m intel motor` | Programa el radar y los candidatos; ejecuta dossieres y borradores |
| `panel` | `python -m intel panel` | Web con contraseña para elegir temas y revisar piezas |

El panel solo encola trabajos; el motor los ejecuta. Los dos usan la misma imagen.

## Variables

| Variable | Dónde | Para qué |
|---|---|---|
| `DATABASE_URL` | motor, panel | Referencia a Postgres |
| `ANTHROPIC_API_KEY` | compartida | Puntuación, candidatos, dossier, redacción. Sin ella el radar solo recoge y archiva |
| `EXA_API_KEY` | compartida | Búsqueda web del dossier. Sin ella el dossier usa solo el archivo propio |
| `PANEL_PASSWORD` | panel | Contraseña del panel (el usuario puede ser cualquiera) |
| `MODELO_PUNTUACION`, `MODELO_ANALISIS`, `MODELO_REDACCION` | opcional | Modelos por etapa |
| `RADAR_CADA_HORAS` | opcional | Por defecto 6 |
| `CANDIDATOS_DIA`, `CANDIDATOS_HORA_UTC` | opcional | Por defecto jueves (3) a las 12:00 UTC |
| `NAVEGADOR` | opcional | `0` desactiva los niveles de navegador |

## Qué se edita y dónde

- **Fuentes**: `config/fuentes.yaml`. Al desplegar, el registro se sincroniza; la salud de cada fuente se ve en el panel.
- **Ediciones** (público, criterio, número de piezas): `config/ediciones.yaml`.
- **Formato de la pieza**: `config/guia_pieza.md`.

## Prueba local

```
DATABASE_URL=postgresql://... python tests/prueba_integral.py
```

Levanta fuentes falsas en local, simula a Claude y recorre el camino completo. Borra las tablas:
no usar contra producción.

## Límites conocidos

- La búsqueda en el archivo es por palabras (texto completo de Postgres), no semántica.
- Los datos de SECMCA y SIECA de Morazania aún no están conectados al dossier.
- Redes sociales y vídeo quedan fuera: se investigan a mano cuando un tema lo pide.
