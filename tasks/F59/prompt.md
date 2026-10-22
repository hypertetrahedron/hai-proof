Feature request for dateparser:

I parse dates scraped from Indian news sites, and strings like `"February 03, 2018 07:18 IST"` come back with a +02:00 offset, because dateparser reads `IST` as Israel Standard Time. For my data it is always Indian Standard Time (+05:30). `IST` isn't the only abbreviation with several meanings, and I can't pick the right one for everybody, so I need some way to tell dateparser what an abbreviation means in my data and have it respected whenever it reads a date.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
