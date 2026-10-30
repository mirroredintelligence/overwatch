## Known issues

| U32 | Q-RES-CLEAR-ROOT-RELS now spares HAS_CREDENTIAL and HAS_DEVICE (a save used to delete a practitioner's PIN credential, lock and devices); any other relationship a non-resource writer hangs from a resource root is still deleted by a save of that resource | resource_store.py | a new store (not the resource store) hangs a node from a Practitioner, PractitionerRole, Organization or HealthcareService root: add its type to LOCAL_RELATIONSHIP_TYPES and to the clear statement |
