"""Country codes, translations, and admin-dropdown helpers.

A flat dict of ISO 3166-1 alpha-2 codes → `{"en": ..., "es": ...}` covering
every country and territory in the standard. The `location.country` column
stores the code; this module produces a localised display name at render time
via `country_name(code, lang)` and the admin form's `<select>` options via
`country_choices(lang)`.

Spanish translations follow the common conventions used by ISO publications
(Spain's RAE / Unicode CLDR forms where there's no single canonical Spanish).
Add or correct entries here — the seed loader, the admin form, and the
public templates all read from `COUNTRIES`.
"""

from __future__ import annotations


# Default country code applied when the seed file or admin form sends an
# empty / unknown value. Anceu (Galicia, Spain) is the host build's home,
# but a fork should feel free to change this.
DEFAULT_COUNTRY: str = "ES"


# ISO 3166-1 alpha-2 → display names. Ordered alphabetically by code.
COUNTRIES: dict[str, dict[str, str]] = {
    "AD": {"en": "Andorra", "es": "Andorra"},
    "AE": {"en": "United Arab Emirates", "es": "Emiratos Árabes Unidos"},
    "AF": {"en": "Afghanistan", "es": "Afganistán"},
    "AG": {"en": "Antigua and Barbuda", "es": "Antigua y Barbuda"},
    "AI": {"en": "Anguilla", "es": "Anguila"},
    "AL": {"en": "Albania", "es": "Albania"},
    "AM": {"en": "Armenia", "es": "Armenia"},
    "AO": {"en": "Angola", "es": "Angola"},
    "AQ": {"en": "Antarctica", "es": "Antártida"},
    "AR": {"en": "Argentina", "es": "Argentina"},
    "AS": {"en": "American Samoa", "es": "Samoa Americana"},
    "AT": {"en": "Austria", "es": "Austria"},
    "AU": {"en": "Australia", "es": "Australia"},
    "AW": {"en": "Aruba", "es": "Aruba"},
    "AX": {"en": "Åland Islands", "es": "Islas Åland"},
    "AZ": {"en": "Azerbaijan", "es": "Azerbaiyán"},
    "BA": {"en": "Bosnia and Herzegovina", "es": "Bosnia y Herzegovina"},
    "BB": {"en": "Barbados", "es": "Barbados"},
    "BD": {"en": "Bangladesh", "es": "Bangladés"},
    "BE": {"en": "Belgium", "es": "Bélgica"},
    "BF": {"en": "Burkina Faso", "es": "Burkina Faso"},
    "BG": {"en": "Bulgaria", "es": "Bulgaria"},
    "BH": {"en": "Bahrain", "es": "Baréin"},
    "BI": {"en": "Burundi", "es": "Burundi"},
    "BJ": {"en": "Benin", "es": "Benín"},
    "BL": {"en": "Saint Barthélemy", "es": "San Bartolomé"},
    "BM": {"en": "Bermuda", "es": "Bermudas"},
    "BN": {"en": "Brunei Darussalam", "es": "Brunéi"},
    "BO": {"en": "Bolivia", "es": "Bolivia"},
    "BQ": {"en": "Bonaire, Sint Eustatius and Saba", "es": "Bonaire, San Eustaquio y Saba"},
    "BR": {"en": "Brazil", "es": "Brasil"},
    "BS": {"en": "Bahamas", "es": "Bahamas"},
    "BT": {"en": "Bhutan", "es": "Bután"},
    "BV": {"en": "Bouvet Island", "es": "Isla Bouvet"},
    "BW": {"en": "Botswana", "es": "Botsuana"},
    "BY": {"en": "Belarus", "es": "Bielorrusia"},
    "BZ": {"en": "Belize", "es": "Belice"},
    "CA": {"en": "Canada", "es": "Canadá"},
    "CC": {"en": "Cocos (Keeling) Islands", "es": "Islas Cocos"},
    "CD": {"en": "Congo (Democratic Republic)", "es": "Congo (República Democrática)"},
    "CF": {"en": "Central African Republic", "es": "República Centroafricana"},
    "CG": {"en": "Congo", "es": "Congo"},
    "CH": {"en": "Switzerland", "es": "Suiza"},
    "CI": {"en": "Côte d’Ivoire", "es": "Costa de Marfil"},
    "CK": {"en": "Cook Islands", "es": "Islas Cook"},
    "CL": {"en": "Chile", "es": "Chile"},
    "CM": {"en": "Cameroon", "es": "Camerún"},
    "CN": {"en": "China", "es": "China"},
    "CO": {"en": "Colombia", "es": "Colombia"},
    "CR": {"en": "Costa Rica", "es": "Costa Rica"},
    "CU": {"en": "Cuba", "es": "Cuba"},
    "CV": {"en": "Cabo Verde", "es": "Cabo Verde"},
    "CW": {"en": "Curaçao", "es": "Curazao"},
    "CX": {"en": "Christmas Island", "es": "Isla de Navidad"},
    "CY": {"en": "Cyprus", "es": "Chipre"},
    "CZ": {"en": "Czechia", "es": "Chequia"},
    "DE": {"en": "Germany", "es": "Alemania"},
    "DJ": {"en": "Djibouti", "es": "Yibuti"},
    "DK": {"en": "Denmark", "es": "Dinamarca"},
    "DM": {"en": "Dominica", "es": "Dominica"},
    "DO": {"en": "Dominican Republic", "es": "República Dominicana"},
    "DZ": {"en": "Algeria", "es": "Argelia"},
    "EC": {"en": "Ecuador", "es": "Ecuador"},
    "EE": {"en": "Estonia", "es": "Estonia"},
    "EG": {"en": "Egypt", "es": "Egipto"},
    "EH": {"en": "Western Sahara", "es": "Sáhara Occidental"},
    "ER": {"en": "Eritrea", "es": "Eritrea"},
    "ES": {"en": "Spain", "es": "España"},
    "ET": {"en": "Ethiopia", "es": "Etiopía"},
    "FI": {"en": "Finland", "es": "Finlandia"},
    "FJ": {"en": "Fiji", "es": "Fiyi"},
    "FK": {"en": "Falkland Islands", "es": "Islas Malvinas"},
    "FM": {"en": "Micronesia", "es": "Micronesia"},
    "FO": {"en": "Faroe Islands", "es": "Islas Feroe"},
    "FR": {"en": "France", "es": "Francia"},
    "GA": {"en": "Gabon", "es": "Gabón"},
    "GB": {"en": "United Kingdom", "es": "Reino Unido"},
    "GD": {"en": "Grenada", "es": "Granada"},
    "GE": {"en": "Georgia", "es": "Georgia"},
    "GF": {"en": "French Guiana", "es": "Guayana Francesa"},
    "GG": {"en": "Guernsey", "es": "Guernsey"},
    "GH": {"en": "Ghana", "es": "Ghana"},
    "GI": {"en": "Gibraltar", "es": "Gibraltar"},
    "GL": {"en": "Greenland", "es": "Groenlandia"},
    "GM": {"en": "Gambia", "es": "Gambia"},
    "GN": {"en": "Guinea", "es": "Guinea"},
    "GP": {"en": "Guadeloupe", "es": "Guadalupe"},
    "GQ": {"en": "Equatorial Guinea", "es": "Guinea Ecuatorial"},
    "GR": {"en": "Greece", "es": "Grecia"},
    "GS": {"en": "South Georgia and the South Sandwich Islands", "es": "Islas Georgias del Sur y Sandwich del Sur"},
    "GT": {"en": "Guatemala", "es": "Guatemala"},
    "GU": {"en": "Guam", "es": "Guam"},
    "GW": {"en": "Guinea-Bissau", "es": "Guinea-Bisáu"},
    "GY": {"en": "Guyana", "es": "Guyana"},
    "HK": {"en": "Hong Kong", "es": "Hong Kong"},
    "HM": {"en": "Heard Island and McDonald Islands", "es": "Islas Heard y McDonald"},
    "HN": {"en": "Honduras", "es": "Honduras"},
    "HR": {"en": "Croatia", "es": "Croacia"},
    "HT": {"en": "Haiti", "es": "Haití"},
    "HU": {"en": "Hungary", "es": "Hungría"},
    "ID": {"en": "Indonesia", "es": "Indonesia"},
    "IE": {"en": "Ireland", "es": "Irlanda"},
    "IL": {"en": "Israel", "es": "Israel"},
    "IM": {"en": "Isle of Man", "es": "Isla de Man"},
    "IN": {"en": "India", "es": "India"},
    "IO": {"en": "British Indian Ocean Territory", "es": "Territorio Británico del Océano Índico"},
    "IQ": {"en": "Iraq", "es": "Irak"},
    "IR": {"en": "Iran", "es": "Irán"},
    "IS": {"en": "Iceland", "es": "Islandia"},
    "IT": {"en": "Italy", "es": "Italia"},
    "JE": {"en": "Jersey", "es": "Jersey"},
    "JM": {"en": "Jamaica", "es": "Jamaica"},
    "JO": {"en": "Jordan", "es": "Jordania"},
    "JP": {"en": "Japan", "es": "Japón"},
    "KE": {"en": "Kenya", "es": "Kenia"},
    "KG": {"en": "Kyrgyzstan", "es": "Kirguistán"},
    "KH": {"en": "Cambodia", "es": "Camboya"},
    "KI": {"en": "Kiribati", "es": "Kiribati"},
    "KM": {"en": "Comoros", "es": "Comoras"},
    "KN": {"en": "Saint Kitts and Nevis", "es": "San Cristóbal y Nieves"},
    "KP": {"en": "North Korea", "es": "Corea del Norte"},
    "KR": {"en": "South Korea", "es": "Corea del Sur"},
    "KW": {"en": "Kuwait", "es": "Kuwait"},
    "KY": {"en": "Cayman Islands", "es": "Islas Caimán"},
    "KZ": {"en": "Kazakhstan", "es": "Kazajistán"},
    "LA": {"en": "Laos", "es": "Laos"},
    "LB": {"en": "Lebanon", "es": "Líbano"},
    "LC": {"en": "Saint Lucia", "es": "Santa Lucía"},
    "LI": {"en": "Liechtenstein", "es": "Liechtenstein"},
    "LK": {"en": "Sri Lanka", "es": "Sri Lanka"},
    "LR": {"en": "Liberia", "es": "Liberia"},
    "LS": {"en": "Lesotho", "es": "Lesoto"},
    "LT": {"en": "Lithuania", "es": "Lituania"},
    "LU": {"en": "Luxembourg", "es": "Luxemburgo"},
    "LV": {"en": "Latvia", "es": "Letonia"},
    "LY": {"en": "Libya", "es": "Libia"},
    "MA": {"en": "Morocco", "es": "Marruecos"},
    "MC": {"en": "Monaco", "es": "Mónaco"},
    "MD": {"en": "Moldova", "es": "Moldavia"},
    "ME": {"en": "Montenegro", "es": "Montenegro"},
    "MF": {"en": "Saint Martin (French part)", "es": "San Martín (parte francesa)"},
    "MG": {"en": "Madagascar", "es": "Madagascar"},
    "MH": {"en": "Marshall Islands", "es": "Islas Marshall"},
    "MK": {"en": "North Macedonia", "es": "Macedonia del Norte"},
    "ML": {"en": "Mali", "es": "Mali"},
    "MM": {"en": "Myanmar", "es": "Birmania"},
    "MN": {"en": "Mongolia", "es": "Mongolia"},
    "MO": {"en": "Macao", "es": "Macao"},
    "MP": {"en": "Northern Mariana Islands", "es": "Islas Marianas del Norte"},
    "MQ": {"en": "Martinique", "es": "Martinica"},
    "MR": {"en": "Mauritania", "es": "Mauritania"},
    "MS": {"en": "Montserrat", "es": "Montserrat"},
    "MT": {"en": "Malta", "es": "Malta"},
    "MU": {"en": "Mauritius", "es": "Mauricio"},
    "MV": {"en": "Maldives", "es": "Maldivas"},
    "MW": {"en": "Malawi", "es": "Malaui"},
    "MX": {"en": "Mexico", "es": "México"},
    "MY": {"en": "Malaysia", "es": "Malasia"},
    "MZ": {"en": "Mozambique", "es": "Mozambique"},
    "NA": {"en": "Namibia", "es": "Namibia"},
    "NC": {"en": "New Caledonia", "es": "Nueva Caledonia"},
    "NE": {"en": "Niger", "es": "Níger"},
    "NF": {"en": "Norfolk Island", "es": "Isla Norfolk"},
    "NG": {"en": "Nigeria", "es": "Nigeria"},
    "NI": {"en": "Nicaragua", "es": "Nicaragua"},
    "NL": {"en": "Netherlands", "es": "Países Bajos"},
    "NO": {"en": "Norway", "es": "Noruega"},
    "NP": {"en": "Nepal", "es": "Nepal"},
    "NR": {"en": "Nauru", "es": "Nauru"},
    "NU": {"en": "Niue", "es": "Niue"},
    "NZ": {"en": "New Zealand", "es": "Nueva Zelanda"},
    "OM": {"en": "Oman", "es": "Omán"},
    "PA": {"en": "Panama", "es": "Panamá"},
    "PE": {"en": "Peru", "es": "Perú"},
    "PF": {"en": "French Polynesia", "es": "Polinesia Francesa"},
    "PG": {"en": "Papua New Guinea", "es": "Papúa Nueva Guinea"},
    "PH": {"en": "Philippines", "es": "Filipinas"},
    "PK": {"en": "Pakistan", "es": "Pakistán"},
    "PL": {"en": "Poland", "es": "Polonia"},
    "PM": {"en": "Saint Pierre and Miquelon", "es": "San Pedro y Miquelón"},
    "PN": {"en": "Pitcairn", "es": "Islas Pitcairn"},
    "PR": {"en": "Puerto Rico", "es": "Puerto Rico"},
    "PS": {"en": "Palestine", "es": "Palestina"},
    "PT": {"en": "Portugal", "es": "Portugal"},
    "PW": {"en": "Palau", "es": "Palaos"},
    "PY": {"en": "Paraguay", "es": "Paraguay"},
    "QA": {"en": "Qatar", "es": "Catar"},
    "RE": {"en": "Réunion", "es": "Reunión"},
    "RO": {"en": "Romania", "es": "Rumanía"},
    "RS": {"en": "Serbia", "es": "Serbia"},
    "RU": {"en": "Russia", "es": "Rusia"},
    "RW": {"en": "Rwanda", "es": "Ruanda"},
    "SA": {"en": "Saudi Arabia", "es": "Arabia Saudí"},
    "SB": {"en": "Solomon Islands", "es": "Islas Salomón"},
    "SC": {"en": "Seychelles", "es": "Seychelles"},
    "SD": {"en": "Sudan", "es": "Sudán"},
    "SE": {"en": "Sweden", "es": "Suecia"},
    "SG": {"en": "Singapore", "es": "Singapur"},
    "SH": {"en": "Saint Helena", "es": "Santa Elena"},
    "SI": {"en": "Slovenia", "es": "Eslovenia"},
    "SJ": {"en": "Svalbard and Jan Mayen", "es": "Svalbard y Jan Mayen"},
    "SK": {"en": "Slovakia", "es": "Eslovaquia"},
    "SL": {"en": "Sierra Leone", "es": "Sierra Leona"},
    "SM": {"en": "San Marino", "es": "San Marino"},
    "SN": {"en": "Senegal", "es": "Senegal"},
    "SO": {"en": "Somalia", "es": "Somalia"},
    "SR": {"en": "Suriname", "es": "Surinam"},
    "SS": {"en": "South Sudan", "es": "Sudán del Sur"},
    "ST": {"en": "São Tomé and Príncipe", "es": "Santo Tomé y Príncipe"},
    "SV": {"en": "El Salvador", "es": "El Salvador"},
    "SX": {"en": "Sint Maarten (Dutch part)", "es": "San Martín (parte neerlandesa)"},
    "SY": {"en": "Syria", "es": "Siria"},
    "SZ": {"en": "Eswatini", "es": "Esuatini"},
    "TC": {"en": "Turks and Caicos Islands", "es": "Islas Turcas y Caicos"},
    "TD": {"en": "Chad", "es": "Chad"},
    "TF": {"en": "French Southern Territories", "es": "Tierras Australes y Antárticas Francesas"},
    "TG": {"en": "Togo", "es": "Togo"},
    "TH": {"en": "Thailand", "es": "Tailandia"},
    "TJ": {"en": "Tajikistan", "es": "Tayikistán"},
    "TK": {"en": "Tokelau", "es": "Tokelau"},
    "TL": {"en": "Timor-Leste", "es": "Timor Oriental"},
    "TM": {"en": "Turkmenistan", "es": "Turkmenistán"},
    "TN": {"en": "Tunisia", "es": "Túnez"},
    "TO": {"en": "Tonga", "es": "Tonga"},
    "TR": {"en": "Türkiye", "es": "Turquía"},
    "TT": {"en": "Trinidad and Tobago", "es": "Trinidad y Tobago"},
    "TV": {"en": "Tuvalu", "es": "Tuvalu"},
    "TW": {"en": "Taiwan", "es": "Taiwán"},
    "TZ": {"en": "Tanzania", "es": "Tanzania"},
    "UA": {"en": "Ukraine", "es": "Ucrania"},
    "UG": {"en": "Uganda", "es": "Uganda"},
    "UM": {"en": "United States Minor Outlying Islands", "es": "Islas Ultramarinas Menores de Estados Unidos"},
    "US": {"en": "United States", "es": "Estados Unidos"},
    "UY": {"en": "Uruguay", "es": "Uruguay"},
    "UZ": {"en": "Uzbekistan", "es": "Uzbekistán"},
    "VA": {"en": "Holy See", "es": "Santa Sede"},
    "VC": {"en": "Saint Vincent and the Grenadines", "es": "San Vicente y las Granadinas"},
    "VE": {"en": "Venezuela", "es": "Venezuela"},
    "VG": {"en": "British Virgin Islands", "es": "Islas Vírgenes Británicas"},
    "VI": {"en": "U.S. Virgin Islands", "es": "Islas Vírgenes de los Estados Unidos"},
    "VN": {"en": "Vietnam", "es": "Vietnam"},
    "VU": {"en": "Vanuatu", "es": "Vanuatu"},
    "WF": {"en": "Wallis and Futuna", "es": "Wallis y Futuna"},
    "WS": {"en": "Samoa", "es": "Samoa"},
    "YE": {"en": "Yemen", "es": "Yemen"},
    "YT": {"en": "Mayotte", "es": "Mayotte"},
    "ZA": {"en": "South Africa", "es": "Sudáfrica"},
    "ZM": {"en": "Zambia", "es": "Zambia"},
    "ZW": {"en": "Zimbabwe", "es": "Zimbabue"},
}


# Free-text values that may already be sitting in `location.country` from
# before this module existed. The one-shot data migration in `db.init()` maps
# any row whose value appears here to the corresponding ISO code; unrecognised
# values are left alone (the display layer falls back to the raw string).
# Keep this small and obvious — it is not a translation table, it is a bridge
# for legacy rows.
_LEGACY_NAME_TO_CODE: dict[str, str] = {
    "spain": "ES",
    "españa": "ES",
    "espana": "ES",
    "portugal": "PT",
    "france": "FR",
    "francia": "FR",
    "germany": "DE",
    "alemania": "DE",
    "italy": "IT",
    "italia": "IT",
    "united kingdom": "GB",
    "uk": "GB",
    "reino unido": "GB",
    "ireland": "IE",
    "irlanda": "IE",
    "united states": "US",
    "usa": "US",
    "estados unidos": "US",
}


def country_name(code: str | None, lang: str) -> str:
    """Localised display name for an ISO 3166-1 alpha-2 country code.

    Falls back en→es→the raw input if the code isn't in `COUNTRIES` — so a
    pre-migration row that still holds a free-text country still renders
    something sensible.
    """
    if not code:
        return ""

    entry = COUNTRIES.get(code.upper())
    if entry is not None:
        return entry.get(lang) or entry.get("en") or entry.get("es") or code

    return code


def country_choices(lang: str) -> list[tuple[str, str]]:
    """Sorted `(code, localised_name)` tuples for the admin `<select>`."""
    return sorted(
        ((code, country_name(code, lang)) for code in COUNTRIES),
        key=lambda pair: pair[1].casefold(),
    )


def normalise_country(value: str | None) -> str:
    """Map an incoming value to a known ISO code, or fall back to the default.

    Accepts an already-correct code (case-insensitive), a legacy free-text
    name from `_LEGACY_NAME_TO_CODE`, or anything else (returns
    `DEFAULT_COUNTRY`). Used by the seed loader and the admin form handlers.
    """
    if not value:
        return DEFAULT_COUNTRY

    candidate = value.strip()
    if not candidate:
        return DEFAULT_COUNTRY

    upper = candidate.upper()
    if upper in COUNTRIES:
        return upper

    legacy = _LEGACY_NAME_TO_CODE.get(candidate.casefold())
    if legacy is not None:
        return legacy

    return DEFAULT_COUNTRY


def migrate_legacy_value(value: str | None) -> str | None:
    """Best-effort upgrade of a pre-existing `location.country` value.

    Returns the new code if `value` is a known legacy name; `None` otherwise
    (caller leaves the row untouched). Already-coded values (2-char,
    case-insensitively present in `COUNTRIES`) are recognised so the data
    migration is idempotent — re-running on an already-migrated DB is a no-op.
    """
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    upper = candidate.upper()
    if len(candidate) == 2 and upper in COUNTRIES:
        return upper if candidate != upper else None

    legacy = _LEGACY_NAME_TO_CODE.get(candidate.casefold())

    return legacy
