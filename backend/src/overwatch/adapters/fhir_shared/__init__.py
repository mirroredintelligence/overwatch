"""FHIR mappings that both the inbound routes and the outbound stores use (pure, no I/O).

The inbound and outbound packages may not import each other (the independence contract), so a
mapping both need lives here.
"""
