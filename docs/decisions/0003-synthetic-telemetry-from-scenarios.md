# 3. Made-up incidents, generated from short descriptions

*Decided 21 October 2026.*

**The problem.** We needed incidents with misleading and missing clues, each with a known
right answer. Real incident data isn't available, and couldn't be published anyway.

**What we chose.** Each incident is three short files: the report on-call would write, a
description of what really happened, and the right answer. A program turns the description
into thousands of realistic log lines and measurements, the same every time. Tests make
sure the agents only ever see the report and the data, never the description or the
answer.

**The cost.** The data is only as realistic as the generator, and we wrote the incidents
ourselves, so the results show a direction rather than a general benchmark.
