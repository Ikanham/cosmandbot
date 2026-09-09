import re
import calendar

# Traduction simple pour les mois français
MOIS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


def parse_date_str(date_str: str) -> str | None:
    """
    Convertit 'JJ/MM' ou 'JJ mois' ou '1er mois' en format JJ/MM (str).
    Retourne None si invalide.
    """
    date_str = date_str.strip().lower()

    # Format JJ/MM
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", date_str)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= calendar.monthrange(2000, month)[1]:
            return f"{day:02d}/{month:02d}"
        return None

    # Format JJ mois (ex: 1 février ou 1er février)
    m = re.match(r"^(\d{1,2})(?:er)?\s+([a-zéû]+)$", date_str)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        month = MOIS.get(month_name)
        if month and 1 <= day <= calendar.monthrange(2000, month)[1]:
            return f"{day:02d}/{month:02d}"
        return None

    return None
