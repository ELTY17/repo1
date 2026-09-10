"""La firma se verifica contra el vector de ejemplo que publica Kraken.

Es la unica parte del cliente que no admite "parece que funciona": o produce
exactamente la firma esperada o las peticiones se rechazan. Se comprueba sin
tener cuenta ni clave real.
"""
from bot.kraken import sign

VECTOR = {
    "path": "/0/private/AddOrder",
    "secret": ("kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd"
               "3pd5nE9qa99HAZtuZuj6F1huXg=="),
    "data": {"nonce": 1616492376594, "ordertype": "limit", "pair": "XBTUSD",
             "price": 37500, "type": "buy", "volume": 1.25},
    "expected": ("4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8"
                 "MPtnRfp32bAb0nmbRn6H8ndwLUQ=="),
}


def test_signature_matches_kraken_vector():
    got = sign(VECTOR["path"], VECTOR["data"], VECTOR["secret"])
    assert got == VECTOR["expected"], f"\n  esperada: {VECTOR['expected']}\n  obtenida: {got}"


if __name__ == "__main__":
    test_signature_matches_kraken_vector()
    print("✓ la firma coincide con el vector de ejemplo de Kraken")
