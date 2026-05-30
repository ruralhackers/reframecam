"""UI string storage and the `t()` helper.

Pattern from spec §9.9: a single dict keyed by language. Editable by Rural
Hackers without touching engineering. Key convention: `surface.element.variant`.

Phase 0 populated only site-wide chrome keys. Phase 2 adds the landing-page,
station-chrome, reference-photo cold-start, date-format helpers, and basic
HTML title strings (§9.2, §9.3, §9.4 cold-start, §9.6, §9.8). Phase 3 adds the
viewer aria labels and cold-start microcopy (§9.4 viewer).
Phase 4 adds the upload-flow microcopy for all six §6.2 states plus the §6.8
acknowledgement-panel placeholder copy. Phase 7 adds the §9.8 meta-description
templates, OG `og:locale` codes, and the themed-error microcopy (§10.4).

Per-station story copy and place names live in the seed config (`stations.toml`),
not in this dict — Rural Hackers edit narrative copy there. Only fixed UI
strings live here.
"""

from __future__ import annotations


# The default UI language. The set of languages actually offered to visitors
# is configured in site.toml — see `app.config.SiteConfig.enabled_languages`.
DEFAULT_LANG: str = "en"


# ---------------------------------------------------------------------------
# Date formatting (spec §9.6)
# ---------------------------------------------------------------------------
#
# The stats line wants "marzo de 2024" / "March 2024" (built from the oldest
# active photo's captured_at). Plain dicts of month names so we never touch
# the system locale (which would couple correctness to the deploy host).

MONTH_NAMES: dict[str, tuple[str, ...]] = {
    "es": (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}

# Three-letter abbreviations used by the scrubber's major month labels (§5.5.4).
# Sage-deep mono in the rendered viewer; lowercase to match the spec sketch.
MONTH_ABBR: dict[str, tuple[str, ...]] = {
    "es": (
        "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sep", "oct", "nov", "dic",
    ),
    "en": (
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    ),
}


STRINGS: dict[str, dict[str, str]] = {
    "es": {
        # Site-wide chrome. The wordmark and footer attribution / sign-off are
        # config-driven (site.toml) so a fork rebrands without code changes.
        "html.lang": "es",
        "header.skip_to_main": "Saltar al contenido",
        "language_toggle.aria": "Cambiar idioma",
        "language_toggle.active": "ES",
        "language_toggle.inactive": "EN",
        "page.title": "ReFrame",
        # Page titles + meta (§9.8)
        "landing.title": "ReFrame · Regeneración rural a través del ojo de la comunidad",
        "station.title_template": "{name} · ReFrame",
        "meta.description.landing": (
            "Regeneración rural a través del ojo de la comunidad."
        ),
        "meta.description.station_template": (
            "Mira cómo cambia {name} a lo largo del tiempo, foto a foto."
        ),
        # OG `og:locale`. Spanish-Spain is the local audience; the value is
        # IETF-style with an underscore for OG. EN uses the generic `en_GB`
        # since narrative copy is in British English.
        "meta.og_locale": "es_ES",
        # Themed error pages (§10.4) — friendly, in voice with §2.2.
        "error.404.title": "Página no encontrada · ReFrame",
        "error.404.label": "PÁGINA NO ENCONTRADA",
        "error.404.heading": "No encontramos esta página.",
        "error.404.body": (
            "Puede que el enlace esté desactualizado, o que nunca haya existido. "
            "Vuelve al inicio para empezar de nuevo."
        ),
        "error.404.cta": "Inicio",
        "error.500.title": "Algo no fue bien · ReFrame",
        "error.500.label": "ALGO FALLÓ",
        "error.500.heading": "Algo no fue bien.",
        "error.500.body": (
            "Hemos tenido un problema en nuestro lado. Vuelve a intentarlo en un momento."
        ),
        "error.500.cta": "Inicio",
        # Marketing landing page ("abundant brooks" redesign). Strings are
        # ordered by DOM section — nav, hero, about, quote, locations, setup.
        # ES copy is a stand-in pending Rural Hackers sign-off.
        "nav.locations": "Lugares",
        "nav.setup": "Acoger",
        "landing.hero.badge": "EST. GALICIA 2024",
        "landing.hero.tagline": (
            "Regeneración rural a través del ojo de la comunidad."
        ),
        "landing.intro.label": "EL PROYECTO",
        "landing.intro.heading": "¿Qué es ReFrame?",
        "landing.intro.p1": (
            "ReFrame es una forma libre y de código abierto para que una "
            "comunidad fotografíe cómo cambia su propio paisaje con el tiempo."
        ),
        "landing.intro.p1b": (
            "Creado por "
            "<a href=\"https://ruralhackers.com\" target=\"_blank\" rel=\"noopener\">Rural Hackers</a> "
            "de Anceu, Galicia, convierte la misma vista —tomada por muchas "
            "personas, durante muchos años— en un timelapse compartido al que "
            "cualquiera puede contribuir."
        ),
        "landing.intro.p2": (
            "Cada estación es un soporte de móvil impreso en 3D, instalado "
            "en un punto fijo del paisaje. Escanea su QR, sube una foto y "
            "mira crecer el timelapse."
        ),
        "landing.intro.image_alt": "Una estación de ReFrame en el paisaje.",
        "landing.about.label": "RAÍCES COMUNES",
        "landing.about.heading": (
            "Donde el patrimonio humano se encuentra con el renacer natural."
        ),
        "landing.about.p1": (
            "La regeneración rural no es solo reforestar. Es el diálogo entre "
            "lo construido y lo salvaje."
        ),
        "landing.about.p2": (
            "ReFrame documenta cómo las comunidades habitan, cuidan y sanan "
            "los paisajes que llaman hogar."
        ),
        "landing.about.image_alt": "Anceu, Galicia",
        "landing.quote.body": (
            "Llegar al lugar de partida y conocerlo por primera vez"
        ),
        "landing.quote.attr": "— T.S. Eliot",
        "landing.locations.label": "LA RED",
        "landing.locations.heading": "Nuestro primer capítulo:",
        "landing.locations.heading_place": "Anceu, Galicia",
        "landing.locations.cta": "VER TODOS LOS LUGARES",
        "landing.locations.empty": "Aún no hay lugares. Vuelve pronto.",
        "landing.setup.label": "LA SEMILLA",
        "landing.setup.heading": "Lleva ReFrame a tu comunidad.",
        "landing.setup.p1": (
            "Todo lo que hay detrás de ReFrame es de código abierto: el "
            "soporte de móvil impreso en 3D y la aplicación web que hace "
            "funcionar este sitio."
        ),
        "landing.setup.p2": (
            "Acoge una estación aquí, como parte de nuestra red en "
            "crecimiento, o toma el código y monta tu propio sitio ReFrame. "
            "En cualquier caso, escríbenos y te ayudamos a empezar."
        ),
        "landing.setup.cta": "ACOGER UN LUGAR",
        # /locations page (v2).
        "locations.title": "Lugares · ReFrame",
        "locations.meta_description": (
            "Encuentra todas las estaciones de ReFrame en el mapa y "
            "explóralas por lugar."
        ),
        "locations.heading": "Lugares",
        "locations.map_aria": "Mapa de las estaciones de ReFrame",
        "locations.map_hint": "Usa dos dedos para mover el mapa",
        "locations.empty": "Aún no hay lugares. Vuelve pronto.",
        "locations.host_cta.heading": "¿Tu lugar no está en el mapa?",
        "locations.host_cta.body": (
            "ReFrame es de código abierto y gratuito de usar. Únete a este "
            "mapa como un nuevo lugar, o monta tu propio sitio ReFrame."
        ),
        "locations.host_cta.body_emphasis": (
            "Cuéntanos sobre tu lugar y te ayudamos a empezar."
        ),
        "locations.host_cta.action": "Acoger un lugar",
        # /acoger — community submission form (v2). Copy is a stand-in;
        # Rural Hackers to confirm before launch.
        "host.title": "Acoger un lugar · ReFrame",
        "host.meta_description": (
            "Cuéntale a Rural Hackers un lugar que podría acoger una "
            "estación de ReFrame."
        ),
        "host.heading": "Acoger un lugar",
        "host.intro.p1": (
            "Cuéntanos un sitio que merezca verse cambiar — un mirador, "
            "una orilla, una ladera que se transforma poco a poco."
        ),
        "host.intro.p2": (
            "Te respondemos por correo y te ayudamos a montar una estación, "
            "desde imprimir el soporte libre hasta elegir el ángulo — aquí "
            "en este sitio o en uno propio."
        ),
        "host.field.email.label": "Tu correo electrónico",
        "host.field.location.label": "Lugar aproximado",
        "host.field.location.hint": "Donde sea, p. ej. «Cataluña, España».",
        "host.field.interests.label": "¿Con cuáles te identificas?",
        "host.interest.have_location": "Tengo un lugar concreto en mente",
        "host.interest.can_install": "Puedo instalar el soporte yo mismo/a",
        "host.interest.can_print": (
            "Puedo imprimir el soporte en 3D con el modelo abierto"
        ),
        "host.interest.want_guidance": (
            "Me gustaría que Rural Hackers me orientara"
        ),
        "host.interest.just_curious": "Solo quiero saber más",
        "host.field.notes.label": "¿Algo más? (opcional)",
        "host.submit": "ENVIAR",
        "host.error.missing": (
            "Añade tu correo y un lugar aproximado para que podamos "
            "responderte."
        ),
        "host.error.invalid_email": (
            "No parece un correo válido. Revísalo e inténtalo de nuevo."
        ),
        "host.confirmation.heading": "Gracias. Te escribiremos.",
        "host.confirmation.body": (
            "Hemos recibido tu mensaje y te responderemos por correo. Puede "
            "tardar unos días."
        ),
        "host.confirmation.back": "VOLVER AL INICIO",
        "host.required_indicator": "Obligatorio",
        # Station hero / chrome (§9.3). The meta line sits under the H1 in
        # mono caps; views.station_view builds it from place + country.
        "station.hero.aria": "Imagen reciente del lugar",
        # Story section
        "station.story.heading": "Sobre",
        # Story stats line (§5.3, §9.3)
        "station.stats.with_photos": "{count} contribuciones desde {month} de {year}.",
        "station.stats.empty": "Sin fotos todavía.",
        # Estaciones cercanas — at the bottom of a station page; filtered by
        # great-circle distance from the current station.
        "nearby.heading": "Estaciones cercanas",
        # Timelapse viewer (§5.5, §9.4)
        "viewer.aria.region": "Visor de fotografía repetida",
        "viewer.aria.play": "Reproducir",
        "viewer.aria.pause": "Pausa",
        "viewer.aria.prev": "Foto anterior",
        "viewer.aria.next": "Foto siguiente",
        "viewer.aria.speed": "Velocidad",
        "viewer.aria.scrubber": "Línea de tiempo",
        # Frame-of-total label — shown in the minimal (1–2 photos) state
        # and announced via aria-live whenever the frame changes.
        "viewer.frame_of_total": "Foto {n} de {total}",
        # Empty-state caption shown under the placeholder frame when a station
        # has no uploads yet (sits in the same slot as frame_of_total would).
        "viewer.empty_caption": "Aún no hay fotos",
        # Date-overlay screen-reader longform (numeric overlay stays the same).
        "viewer.sr.date_template": "Foto del {day} de {month} de {year}",
        # Upload flow — section heading (§6.1, always visible)
        "upload.section.heading": "Subir una foto",
        "upload.section.body": (
            "Sube una foto y mírala aparecer en el timelapse al instante."
        ),
        # State 1 — picker (§6.3, §9.5)
        "upload.picker.cta": "Subir una foto",
        "upload.picker.cta_camera": "Hacer una foto",
        "upload.picker.ack": "Al subir, aceptas que la foto sea pública.",
        "upload.picker.ack_link": "Saber más",
        "upload.picker.ack_close": "Cerrar",
        "upload.picker.panel_body": (
            "Al subir tu foto, aceptas que aparezca públicamente en el timelapse "
            "de este lugar y que "
            "<a href=\"https://ruralhackers.com\" target=\"_blank\" rel=\"noopener\">Rural Hackers</a> "
            "pueda usarla en materiales sobre "
            "el proyecto. No recogemos tu nombre ni datos de contacto. Tu foto "
            "se publica de forma anónima."
        ),
        # State 2 — preview + confirm (§6.4, §9.5)
        "upload.preview.heading": "¿Subir esta foto?",
        "upload.preview.confirm": "Subir esta foto",
        "upload.preview.change": "Cambiar",
        "upload.preview.no_preview": "No podemos mostrar una vista previa de esta foto.",
        # State 3 — uploading (§9.5). The {percent} placeholder is filled by JS.
        "upload.uploading.status": "Subiendo… {percent}%",
        "upload.uploading.paused": "En pausa — esperando conexión",
        # State 4 — validating (§9.5)
        "upload.validating.status": "Comprobando foto…",
        "upload.validating.sub": "Comparando con las fotos de referencia…",
        # State 5a — success (§6.7, §9.5)
        "upload.success.heading": "Foto añadida al timelapse",
        "upload.success.body": "Tu foto se une a las demás en el timelapse de arriba.",
        "upload.success.view_cta": "Ver en el timelapse",
        # State 5b — failure microcopy (§6.5, §9.5). Keys match the `error`
        # codes the server / client return. See app/views._upload_view.
        "upload.failure.wrong_file_type.body": (
            "No reconocemos este archivo. Asegúrate de que sea una foto."
        ),
        "upload.failure.wrong_file_type.cta": "Elegir otra",
        "upload.failure.network.body": (
            "Se cortó la conexión. ¿Probamos de nuevo?"
        ),
        "upload.failure.network.cta": "Reintentar",
        "upload.failure.doesnt_match.body": (
            "No hemos podido verificar que sea de aquí. ¿La tomaste desde el soporte?"
        ),
        "upload.failure.doesnt_match.cta": "Elegir otra",
        "upload.failure.too_blurry.body": (
            "La foto se ve borrosa. Inténtalo de nuevo manteniendo el móvil quieto."
        ),
        "upload.failure.too_blurry.cta": "Elegir otra",
        "upload.failure.server_error.body_prefix": "Algo no fue bien. Si vuelve a pasar, ",
        "upload.failure.server_error.body_link": "escríbenos",
        "upload.failure.server_error.body_suffix": ".",
        "upload.failure.server_error.cta": "Reintentar",
        "upload.failure.too_large.body": (
            "Esta foto pesa demasiado para subirla. Prueba con otra."
        ),
        "upload.failure.too_large.cta": "Elegir otra",
        "upload.failure.too_small.body": (
            "La foto tiene una resolución muy baja. Prueba con una cámara de mejor calidad."
        ),
        "upload.failure.too_small.cta": "Elegir otra",
        "upload.failure.not_ready.body": (
            "Esta estación aún no acepta fotos. Vuelve a probar pronto."
        ),
        "upload.failure.not_ready.cta": "Entendido",
        # ARIA labels for non-textual upload UI elements
        "upload.aria.section": "Subir una foto",
        "upload.aria.progress": "Progreso de subida",
        "upload.aria.spinner": "Comprobando",
        # Admin UI (§9.7) — Spanish only; the admin surface has no English variant.
        "admin.page.title": "Administración · ReFrame",
        "admin.heading": "Fotos recientes",
        "admin.column.photo": "Foto",
        "admin.column.place": "Lugar",
        "admin.column.date": "Fecha",
        "admin.column.action": "Acción",
        "admin.action.remove": "Quitar",
        "admin.confirm.message": "¿Quitar esta foto del timelapse?",
        "admin.confirm.confirm": "Sí, quitar",
        "admin.confirm.cancel": "Cancelar",
        "admin.empty": "Aún no hay fotos.",
        "admin.pagination.previous": "← Anteriores",
        "admin.pagination.next": "Siguientes →",
        "admin.removal_reason.label": "Motivo (opcional)",
        "admin.thumb_alt": "Miniatura",
    },
    "en": {
        "html.lang": "en",
        "header.skip_to_main": "Skip to content",
        "language_toggle.aria": "Switch language",
        "language_toggle.active": "EN",
        "language_toggle.inactive": "ES",
        "page.title": "ReFrame",
        "landing.title": "ReFrame · Rural regeneration through the lens of community",
        "station.title_template": "{name} · ReFrame",
        "meta.description.landing": (
            "Rural regeneration through the lens of community."
        ),
        "meta.description.station_template": (
            "See how {name} changes over time, photo by photo."
        ),
        "meta.og_locale": "en_GB",
        "error.404.title": "Page not found · ReFrame",
        "error.404.label": "PAGE NOT FOUND",
        "error.404.heading": "We couldn't find that page.",
        "error.404.body": (
            "The link may be out of date, or may never have existed. "
            "Head home to find your way again."
        ),
        "error.404.cta": "Home",
        "error.500.title": "Something went wrong · ReFrame",
        "error.500.label": "SOMETHING WENT WRONG",
        "error.500.heading": "Something went wrong.",
        "error.500.body": (
            "We hit a problem on our side. Try again in a moment."
        ),
        "error.500.cta": "Home",
        # Marketing landing page ("abundant brooks" redesign).
        "nav.locations": "Locations",
        "nav.setup": "Host",
        "landing.hero.badge": "EST. GALICIA 2024",
        "landing.hero.tagline": (
            "Rural regeneration through the lens of community."
        ),
        "landing.intro.label": "THE PROJECT",
        "landing.intro.heading": "What is ReFrame?",
        "landing.intro.p1": (
            "ReFrame is a free, open-source way for a community to "
            "photograph how its own landscape changes over time."
        ),
        "landing.intro.p1b": (
            "Built by "
            "<a href=\"https://ruralhackers.com\" target=\"_blank\" rel=\"noopener\">Rural Hackers</a> "
            "of Anceu, Galicia, it turns the same view — taken by many people, "
            "over many years — into a shared timelapse anyone can add to."
        ),
        "landing.intro.p2": (
            "Each station is a 3D-printed phone holder fixed at a chosen "
            "viewpoint. Scan its QR, upload a photo, and watch the "
            "timelapse grow."
        ),
        "landing.intro.image_alt": "A ReFrame station in the landscape.",
        "landing.about.label": "SHARED ROOTS",
        "landing.about.heading": (
            "Where human heritage meets natural regrowth."
        ),
        "landing.about.p1": (
            "Rural regeneration isn't just about reforestation. It's about "
            "the dialogue between the built environment and the wild."
        ),
        "landing.about.p2": (
            "ReFrame documents how communities inhabit, protect, and heal "
            "the landscapes they call home."
        ),
        "landing.about.image_alt": "Anceu, Galicia",
        "landing.quote.body": (
            "To arrive where we started and know the place for the first time"
        ),
        "landing.quote.attr": "— T.S. Eliot",
        "landing.locations.label": "THE NETWORK",
        "landing.locations.heading": "Our First Chapter:",
        "landing.locations.heading_place": "Galicia, Spain",
        "landing.locations.cta": "EXPLORE ALL LOCATIONS",
        "landing.locations.empty": "No locations yet. Check back soon.",
        "landing.setup.label": "THE SEED",
        "landing.setup.heading": "Bring ReFrame to your community.",
        "landing.setup.p1": (
            "Everything behind ReFrame is open source — the 3D-printed "
            "phone holder and the web app that runs this site."
        ),
        "landing.setup.p2": (
            "Host a station here as part of our growing network, or take "
            "the code and run a ReFrame site of your own. Either way, get "
            "in touch and we'll help you start."
        ),
        "landing.setup.cta": "HOST A LOCATION",
        # /locations page (v2).
        "locations.title": "Locations · ReFrame",
        "locations.meta_description": (
            "Find every ReFrame station on the map, and browse them by place."
        ),
        "locations.heading": "Locations",
        "locations.map_aria": "Map of ReFrame station locations",
        "locations.map_hint": "Use two fingers to move the map",
        "locations.empty": "No locations yet. Check back soon.",
        "locations.host_cta.heading": "Don't see your community here?",
        "locations.host_cta.body": (
            "ReFrame is open source and free to run. Join this map as a new "
            "location, or stand up a ReFrame site of your own."
        ),
        "locations.host_cta.body_emphasis": (
            "Tell us about your place and we'll help you start."
        ),
        "locations.host_cta.action": "Host a location",
        # /host — community submission form (v2). Copy is a stand-in;
        # Rural Hackers to confirm before launch.
        "host.title": "Host a location · ReFrame",
        "host.meta_description": (
            "Tell Rural Hackers about a place that could host a ReFrame "
            "station."
        ),
        "host.heading": "Host a location",
        "host.intro.p1": (
            "Tell us about a place worth watching change — a viewpoint, "
            "a shoreline, a hillside slowly transforming."
        ),
        "host.intro.p2": (
            "We'll reply by email and help you set up a station, from "
            "printing the open-source holder to choosing the angle — here "
            "on this site, or on one of your own."
        ),
        "host.field.email.label": "Your email",
        "host.field.location.label": "Rough location",
        "host.field.location.hint": "Anywhere, e.g. \"Catalonia, Spain\".",
        "host.field.interests.label": "Which of these sound like you?",
        "host.interest.have_location": "I have a specific location in mind",
        "host.interest.can_install": "I can install the holder myself",
        "host.interest.can_print": (
            "I'm happy to 3D print the holder from the open-source model"
        ),
        "host.interest.want_guidance": "I'd like guidance from Rural Hackers",
        "host.interest.just_curious": "I'm just interested in learning more",
        "host.field.notes.label": "Anything else? (optional)",
        "host.submit": "SEND",
        "host.error.missing": (
            "Please add your email and a rough location so we can reply."
        ),
        "host.error.invalid_email": (
            "That doesn't look like a valid email. Check it and try again."
        ),
        "host.confirmation.heading": "Thanks. We'll be in touch.",
        "host.confirmation.body": (
            "We've got your message and will reply by email. It might take a "
            "few days."
        ),
        "host.confirmation.back": "BACK TO HOME",
        "host.required_indicator": "Required",
        "station.hero.aria": "Recent image of this place",
        "station.story.heading": "About",
        "station.stats.with_photos": "{count} contributions since {month} {year}.",
        "station.stats.empty": "No photos yet.",
        "nearby.heading": "Nearby stations",
        "viewer.aria.region": "Repeat-photography viewer",
        "viewer.aria.play": "Play",
        "viewer.aria.pause": "Pause",
        "viewer.aria.prev": "Previous photo",
        "viewer.aria.next": "Next photo",
        "viewer.aria.speed": "Speed",
        "viewer.aria.scrubber": "Timeline",
        "viewer.frame_of_total": "Photo {n} of {total}",
        "viewer.empty_caption": "No photos uploaded",
        "viewer.sr.date_template": "Photo from {day} {month} {year}",
        "upload.section.heading": "Upload a photo",
        "upload.section.body": (
            "Upload a photo and see it immediately on the timelapse."
        ),
        "upload.picker.cta": "Upload a photo",
        "upload.picker.cta_camera": "Take a photo",
        "upload.picker.ack": "By uploading, you agree the photo will be public.",
        "upload.picker.ack_link": "Learn more",
        "upload.picker.ack_close": "Close",
        "upload.picker.panel_body": (
            "By uploading your photo, you agree it will appear publicly in this "
            "place's timelapse and that "
            "<a href=\"https://ruralhackers.com\" target=\"_blank\" rel=\"noopener\">Rural Hackers</a> "
            "may use it in materials "
            "about the project. We don't collect your name or contact details. "
            "Your photo is published anonymously."
        ),
        "upload.preview.heading": "Upload this photo?",
        "upload.preview.confirm": "Upload this photo",
        "upload.preview.change": "Change",
        "upload.preview.no_preview": "We can't show a preview of this photo.",
        "upload.uploading.status": "Uploading… {percent}%",
        "upload.uploading.paused": "Paused — waiting for connection",
        "upload.validating.status": "Checking photo…",
        "upload.validating.sub": "Comparing with the reference photos…",
        "upload.success.heading": "Photo added to the timelapse",
        "upload.success.body": "Your photo joins the others in the timelapse above.",
        "upload.success.view_cta": "View in timelapse",
        "upload.failure.wrong_file_type.body": (
            "We don't recognise this file. Make sure it's a photo."
        ),
        "upload.failure.wrong_file_type.cta": "Choose another",
        "upload.failure.network.body": "The connection dropped. Try again?",
        "upload.failure.network.cta": "Try again",
        "upload.failure.doesnt_match.body": (
            "We couldn't verify this was taken here. Did you take it from the holder?"
        ),
        "upload.failure.doesnt_match.cta": "Choose another",
        "upload.failure.too_blurry.body": (
            "The photo looks blurry. Try again, holding the phone still."
        ),
        "upload.failure.too_blurry.cta": "Choose another",
        "upload.failure.server_error.body_prefix": "Something went wrong. If it happens again, ",
        "upload.failure.server_error.body_link": "get in touch",
        "upload.failure.server_error.body_suffix": ".",
        "upload.failure.server_error.cta": "Try again",
        "upload.failure.too_large.body": (
            "That photo's too big to upload. Try another one."
        ),
        "upload.failure.too_large.cta": "Choose another",
        "upload.failure.too_small.body": (
            "That photo's resolution is too low. Try a higher-quality camera."
        ),
        "upload.failure.too_small.cta": "Choose another",
        "upload.failure.not_ready.body": (
            "This station isn't accepting photos yet. Check back soon."
        ),
        "upload.failure.not_ready.cta": "OK",
        "upload.aria.section": "Upload a photo",
        "upload.aria.progress": "Upload progress",
        "upload.aria.spinner": "Checking",
    },
}


def t(key: str, lang: str) -> str:
    """Resolve a UI string by key and language.

    Falls back to English, then Spanish, then the bare key. The fallback is a
    safety net for partial translations during development — it should never
    fire in shipped code.
    """
    table = STRINGS.get(lang)
    if table is not None and key in table:
        return table[key]
    if key in STRINGS["en"]:
        return STRINGS["en"][key]

    return STRINGS["es"].get(key, key)


def other_lang(lang: str) -> str:
    return "en" if lang == "es" else "es"


def month_name(lang: str, month: int) -> str:
    """Return the localised month name for `month` in 1–12."""
    names = MONTH_NAMES.get(lang) or MONTH_NAMES[DEFAULT_LANG]

    return names[month - 1]


def month_abbr(lang: str, month: int) -> str:
    """Return the three-letter localised month abbreviation for `month` in 1–12."""
    names = MONTH_ABBR.get(lang) or MONTH_ABBR[DEFAULT_LANG]

    return names[month - 1]
