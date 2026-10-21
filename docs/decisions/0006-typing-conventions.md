# 6. How the code describes its data

*Decided 21 October 2026.*

**The problem.** The code mixed several ways of describing data, such as fixed lists of
allowed values and the shape of a record, with no rule for when to use which.

**What we chose.** A named list for any set of values used in more than one place, such as
the kinds of change or the agents' roles, so a typo is caught straight away. Anything that
comes from outside the program (a file, the AI's answer, a tool's request) is checked when
it arrives. Values the program creates for its own use are not, which keeps it fast.

**The cost.** Some care is needed when adding a value, to put it in the right list.
