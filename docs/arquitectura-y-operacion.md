# Sistema de inteligencia: arquitectura y operación

Estado a 4 de octubre de 2026. Este documento recoge qué está desplegado, por qué se diseñó así
y cómo se opera semana a semana.

## Qué es

Un sistema que recopila información de fuentes públicas y la convierte en material para piezas
semanales de análisis en tres dominios: geopolítica, ciberriesgo estratégico y transformación
digital financiera. Geopolítica tiene dos ediciones que comparten toda la maquinaria y solo
difieren en el criterio editorial: una global y otra pensada para Centroamérica y Latinoamérica.

La referencia de formato es el informe semanal de política internacional analizado al inicio del
proyecto: piezas de 700 a 900 palabras, en prosa, sin gráficos ni notas, que parten de un hecho
con sus cifras y cierran con una tesis que sobrevive a la noticia. Esa publicación sirve como
modelo de formato, no como insumo: el sistema no la ingiere ni la reescribe.

El reparto de papeles es deliberado. El sistema recoge, ordena, propone y comprueba. La elección
del tema, la tesis y la aprobación de cada pieza son decisiones del editor.

## Dónde vive

| Pieza | Ubicación |
|---|---|
| Código | Repositorio `Shatior/InteligenciaAutomatizada`, rama `main` |
| Infraestructura | Proyecto `inteligencia-automatizada` en Railway, entorno `production` |
| Panel | `https://panel-production-55a0.up.railway.app` (usuario cualquiera; contraseña en la variable `PANEL_PASSWORD` del servicio `panel`) |

El proyecto de Railway es nuevo y está separado de `morazania`. Cada `push` a `main` redespliega
los dos servicios.

### Servicios

| Servicio | Qué hace |
|---|---|
| `Postgres` | Archivo de items, cola de trabajos, dossieres, piezas y registro de consumo |
| `motor` | Programa el radar y los candidatos; ejecuta dossieres y borradores. No tiene dominio público |
| `panel` | Web con contraseña para ver el radar, elegir temas y revisar piezas. Solo encola trabajos |

Motor y panel usan la misma imagen (Python 3.12 con Chromium). Separarlos aísla la navegación
automatizada de la única superficie expuesta a internet.

## El ciclo

1. **Radar, cada seis horas.** Lee las fuentes activas del registro, trae el texto completo de lo
   nuevo, marca duplicados por titular y puntúa cada item.
2. **Candidatos, los jueves a las 06:00 de Tegucigalpa.** Por cada edición, agrupa lo mejor de los
   últimos siete días en temas, cada uno con su hecho, su porqué y dos o tres tesis posibles.
3. **Dossier, a demanda.** Al elegir un candidato en el panel (o escribir un tema libre), el motor
   planifica búsquedas, reúne hasta veinte fuentes y extrae hechos, contexto, voces,
   contraargumentos y lagunas.
4. **Pieza, a demanda.** Elegida la tesis, redacta el borrador con la guía de formato y lo audita
   contra el dossier.
5. **Revisión.** El editor corrige, vuelve a verificar si quiere, aprueba y descarga en Markdown.

### Dos notas por item

Cada item recibe una nota global (magnitud, novedad, riqueza de datos) y una nota regional (efecto
sobre Centroamérica y su sector financiero, ocurra donde ocurra el hecho). La edición global
ordena por la primera; la regional, la de ciberriesgo y la de transformación digital, por la
segunda. Los avisos de ciberseguridad puramente técnicos se penalizan a la mitad; los hechos que
cruzan dos dominios reciben una bonificación.

### Ediciones

| Edición | Dominios | Ordena por | Piezas objetivo |
|---|---|---|---|
| Geopolítica global | geopolítica, macro | nota global | 3 |
| Geopolítica Centroamérica y Latinoamérica | geopolítica, macro | nota regional | 3 |
| Ciberriesgo estratégico | ciber | nota regional | 2 |
| Transformación digital financiera | transformación | nota regional | 2 |

Público, criterio e instrucción de cierre de cada una están en `config/ediciones.yaml`. La
edición regional pide un párrafo de implicaciones para Centroamérica antes del cierre.

## Papel de cada herramienta

| Herramienta | Papel en producción |
|---|---|
| Scrapling | Motor de obtención, usado como librería: HTTP con huella de navegador, Chromium para páginas con JavaScript y navegador sigiloso solo donde el registro lo autoriza |
| Exa | Búsqueda semántica para el dossier, por API directa |
| Claude | Puntuación (modelo rápido), candidatos, extracción del dossier, redacción y auditoría |
| feedparser, trafilatura, PyMuPDF | Lectura de feeds, extracción del texto principal y lectura de PDF |
| Agent-Reach | Fuera de producción. Queda como herramienta de investigación manual; lo que aporta de forma estable (Exa) está integrado directamente |
| ScrapeGraphAI | Fuera de producción. La extracción estructurada la hace Claude con esquema fijo, sin otra dependencia |
| MCP de Scrapling | No se despliega: un proceso desatendido no necesita un agente en medio |

## Salvaguardas contra datos inventados

Con texto generado, el riesgo principal es una cifra inventada o desactualizada. Hay tres barreras:

1. Un candidato solo se guarda si apunta a items reales del radar.
2. Cada hecho del dossier lleva una cita literal y el número de su fuente. Un programa comprueba
   que la cita aparece en el texto de esa fuente; lo que no se localiza queda como «no
   verificado» y el redactor tiene instrucción de no usarlo.
3. Tras redactar, se cotejan por programa todas las cifras del borrador contra el dossier y un
   segundo paso del modelo busca afirmaciones sin respaldo. El panel muestra ambas listas junto
   al texto.

Ninguna sustituye la lectura del editor: las barreras detectan lo que no está en el dossier, no
si el dossier refleja bien la realidad.

## Registro de fuentes

`config/fuentes.yaml` es el activo más valioso y el único sitio donde se añaden, corrigen o
apagan fuentes. Cada una lleva dominio, región, tipo y fiabilidad en escala Admiralty
(A oficial, B establecida, C desigual). La salud de cada fuente se ve en la página «Fuentes».

Estado tras las primeras pasadas: 94 fuentes en el registro, 82 activas, 81 respondiendo. Las
doce apagadas conservan su motivo en el registro:

| Fuente | Motivo |
|---|---|
| FMI (noticias y blog), Chatham House | Rechazan lectores automáticos incluso con navegador; requerirían el nivel sigiloso |
| Brookings, El Faro | Sin feed y con portada pintada por JavaScript; falta definir el patrón de enlaces |
| BID (dos blogs) | El blog se mudó y ya no publica feed |
| Banco Mundial (blogs) | El feed publicado ya no existe |
| Forbes Centroamérica, El Diario de Hoy, Fintech Futures | El servidor rechaza el feed |
| Global Americans | Certificado TLS del sitio no válido |

El nivel sigiloso, que resuelve protecciones de Cloudflare, no está activado en ninguna fuente.
Es una decisión por fuente y del editor, porque puede ir contra los términos de uso del sitio.
Las fuentes de pago se marcan `solo_feed: true`: se trabaja con su titular y resumen.

## Variables

| Variable | Dónde | Estado |
|---|---|---|
| `DATABASE_URL` | motor y panel | Configurada (referencia a Postgres) |
| `PANEL_PASSWORD` | panel | Configurada |
| `ANTHROPIC_API_KEY` | variable compartida del proyecto | **Pendiente** |
| `EXA_API_KEY` | variable compartida del proyecto | **Pendiente** |

Motor y panel ya leen las dos claves como `${{shared.…}}`; basta crearlas como variables
compartidas del entorno. Sin la de Anthropic el radar recoge y archiva, pero no puntúa, no propone
temas y no redacta. Sin la de Exa el dossier usa solo el archivo propio.

Opcionales: `MODELO_PUNTUACION`, `MODELO_ANALISIS`, `MODELO_REDACCION`, `RADAR_CADA_HORAS`,
`CANDIDATOS_DIA`, `CANDIDATOS_HORA_UTC`, `NAVEGADOR`, `RADAR_AL_ARRANCAR`.

## Qué está comprobado y qué no

Comprobado en producción: despliegue de los tres servicios, esquema de base de datos, recolección
por feed y por portada, obtención de texto por HTTP y con Chromium, deduplicación, cola de
trabajos, programación y las páginas del panel con datos reales (el motor las pinta al arrancar y
deja el resultado en su registro).

Comprobado solo con Claude simulado, en la prueba integral del repositorio: puntuación,
candidatos, dossier, redacción y verificación. Las llamadas reales a Claude y a Exa no se han
ejecutado porque faltan las claves. La primera pasada con claves es la prueba real de los prompts
y hay que leer sus resultados con ojo crítico.

## Pendiente

- Conectar las series de SECMCA y SIECA de Morazania al dossier de la edición regional.
- Búsqueda semántica en el archivo (hoy es por palabras, con el texto completo de Postgres).
- Patrones de portada para El Faro y Brookings.
- Decidir fuente por fuente si se autoriza el nivel sigiloso (FMI, Chatham House).
- El repositorio es público: registro de fuentes y prompts quedan a la vista.
- Pieza piloto doble: un mismo hecho escrito para la edición global y para la regional, para
  comprobar que la diferencia entre ambas es real.
