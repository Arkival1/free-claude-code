"""Trading platforms: the paper account and every live platform FCC connects to.

Each adapter speaks one platform's official API and offers the same small
set of calls (see ``base.Broker``), so the desk works the same way whichever
platform the owner points it at. A new platform is one new adapter.
"""
