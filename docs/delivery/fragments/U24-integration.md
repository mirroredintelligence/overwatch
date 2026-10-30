## Known issues

| U24 | A Communication's about_id is a service id (the store links it to the HealthcareService); the invitation text used the invitation task id, which made a second node under that id and a constraint error | invite_reporter.py | any use case that stores a Communication about something other than a service |
