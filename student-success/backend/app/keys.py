"""DynamoDB key design (single table, two GSIs). See docs/data-dictionary.md.

Access pattern                                  Key used
----------------------------------------------  -----------------------------------------------------------
Student master / insight / records / history    pk = STU#{ds}#{id}
  - master                                      sk = MASTER
  - latest insight (bounded summary)            sk = INSIGHT
  - score history per period                    sk = SCORE#{period}
  - record by category and period               sk = REC#{category}#{period}#{subkey}
  - intervention / note / correction            sk = INT#{id} / NOTE#{int}#{ts} / CORR#{id}
Authorised listing by department and year       gsi1 = DEPT#{ds}#{dept} / Y{year}#{id}     (on INSIGHT items)
Mentor's students                               pk = USER#{sub}, sk = MENTEE#{ds}#{id}
Interventions by owner and status               gsi2 = OWNER#{sub} / {status}#{due}#{id}
Interventions by department                     gsi1 = DEPTINT#{ds}#{dept} / {status}#{due}#{id}
Corrections pending by department               gsi1 = DEPTCORR#{ds}#{dept} / {status}#{created}#{id}
Submissions awaiting verification               gsi1 = VERIFY#{ds} / {ts}#{id}#{sk}     (sparse: only while pending)
Stale insights needing recalculation            gsi2 = STALE#{ds} / {id}   (sparse: only while stale)
Imports                                         pk = IMPORT#{id}; sk = META / ROWS#{batch}; gsi2 = IMPORTS / {created}
User accounts and assignments                   pk = USER#{sub}; sk = PROFILE / ROLE#{role}#{scope} ; gsi2 = USERS / {username}
Subject teachers                                gsi1 = SUBJECT#{dept}#{year}#{subject} / {sub}     (on ROLE items)
Policy and scoring versions                     pk = CONFIG#{kind}; sk = V#{version} / ACTIVE
Audit history                                   pk = AUDIT#{yyyy-mm-dd}; sk = {ts}#{id}; gsi2 = AUDITCAT#{category} / {ts}
Dataset metadata                                pk = DATASET#{ds}; sk = META
"""

from __future__ import annotations


def student(ds: str, sid: str) -> str:
    return f"STU#{ds}#{sid}"


def rec_sk(category: str, period: str, subkey: str = "-") -> str:
    return f"REC#{category}#{period}#{subkey}"


def dept_gsi(ds: str, dept: str) -> str:
    return f"DEPT#{ds}#{dept}"


def user(sub: str) -> str:
    return f"USER#{sub}"


def imp(iid: str) -> str:
    return f"IMPORT#{iid}"
