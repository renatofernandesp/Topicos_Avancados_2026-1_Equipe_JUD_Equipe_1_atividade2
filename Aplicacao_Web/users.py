import bcrypt

def _h(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def check(email: str, password: str) -> bool:
    h = USERS.get(email.lower())
    if not h:
        return False
    return bcrypt.checkpw(password.encode(), h)

USERS = {
    "renato@ufs.com":   _h("re841226"),
    "thomas@ufs.com":   _h("Tz9$nR4w"),
    "eduardo@ufs.com":  _h("Lv3@jQ8e"),
    "poliana@ufs.com":  _h("Wm5!bN6y"),
    "helena@ufs.com":   _h("Dp1#cF0s"),
    "rafael@ufs.com":   _h("Hn4$gV7u"),
}
