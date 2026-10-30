"""The digests of the network registry's global statements (TEN-051).

`test_global_allowlist.py` pins the text of the older global statements; these nineteen are pinned
here by the SHA-256 of their exact text (the same value as in `GLOBAL_STATEMENTS`), and the
parameters, labels and guards of each are pinned in `test_network_registry_statements.py`. A change
to one of them is a change to this file, to `GLOBAL_STATEMENTS` and to the allowlist reason,
reviewed like any security-relevant diff.
"""

from typing import Final

NETWORK_DIGESTS: Final[dict[str, str]] = {
    "Q-NETWORK-GET": ("ff1b798a243eaa94d749d8b5a139f0982b27d3cd2ac06cf2cd75caf36277a08a"),
    "Q-NETWORK-MEMBERSHIPS": ("cf92e1d41dd751757ebd3e335cb2e62626eb945ed2876bc24e3ca61fbb3eb214"),
    "Q-NETWORK-MEMBERSHIPS-OF": (
        "1100de69d690b2e2a4968ad121edec6e1cdc2314410cb37a055665d2ff8c9a70"
    ),
    "Q-NETWORK-MEMBERSHIP-ACTIVE": (
        "17a281a087580bb9b9a8478e5da681907fe0406b80ecec2f5618e75c6aac1397"
    ),
    "Q-NETWORK-GRANT-GET": ("f05af3f980f16e2cfa85ae16f255baff496a037ae8e31f1a3c26822925ca1fa2"),
    "Q-NETWORK-GRANTS": ("aa91b805e94484416c56359dcb1ef3da190b1a32643a722b4adf9b1c1056064e"),
    "Q-NETWORK-GRANTS-OF": ("b78b32896edb14f2f2e911589b63921132f9909c652df6b5cc49ab4e8f4e1672"),
    "Q-NETWORK-GRANT-ACTIVE-FOR": (
        "0a6e6f512ff465e7938b8f45da1d41ce8ab2fb005c0ac1ca058af47e489b4b1b"
    ),
    "Q-NETWORK-LISTING-GET": ("5b4b13d3cd3a3dcecba20e96263461ee5a1710b765705f5d6334bc07dcb9f2f6"),
    "Q-NETWORK-LISTINGS": ("5f7d8ca16ae152b94c7b81cb163e4ef0fc92d01c777ec2533df570b704317a57"),
    "Q-NETWORK-LISTINGS-OF": ("30e09997dd51efc743e928f49d37dfcdb923d5d5f9d63e552373570f85057e8c"),
    "Q-NETWORK-CREATE": ("8732644ba94620e596d76bd7bc82f1506427eaa5aec83f36289684d403f5866d"),
    "Q-NETWORK-SAVE": ("e6295bff855065317509834639d601ea030a0cb0de9693b3aab2efc30cb58dfc"),
    "Q-NETWORK-MEMBER-CREATE": ("1b53050ab54e6ffd5b92f88e0057d923f1a1dc6c157fa89d777b4c022b7a1416"),
    "Q-NETWORK-MEMBER-SAVE": ("6d5dd5a7849237358e0f88eab5891c94f657d8fd44b6abe5c16b39f476ec5e65"),
    "Q-NETWORK-GRANT-CREATE": ("7810b92b84614a07ce88d4859534c9401545bdece5cfcdaba63aa474552c7d93"),
    "Q-NETWORK-GRANT-SAVE": ("49ce209d320428c2231e6e763932dced25f8336f1d5cb890ce76ec0b23aaca6c"),
    "Q-NETWORK-LISTING-CREATE": (
        "5facf39c4da9be8e85618bf69dafe60e4766b0997e750801bbafb31e57007509"
    ),
    "Q-NETWORK-LISTING-SAVE": ("9e65052c9ff7532bdf1b3334be13c1da9f5051ba04b8f0d10ffde4f80b35a2bd"),
}
