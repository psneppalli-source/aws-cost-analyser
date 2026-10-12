# Role matrix

<!-- GENERATED from config/role-matrix.json by `python -m app.tools.render_role_matrix`. Do not edit by hand. -->

Policy version **1.0.0**. Canonical permission policy for the Smart Campus Student Success Platform. The backend enforces this file; docs/role-matrix.md is generated from it. Scopes are resolved from trusted server-side assignments linked to the Cognito user ID, never from browser input.

## Scopes

| Scope | Meaning |
|---|---|
| `college` | Every student in the datasets the user may see |
| `department` | Students in a department the user is assigned to (HOD assignment) |
| `assigned_subject` | Students in a department/year class for a subject the user teaches; record writes must name that subject |
| `assigned_students` | Students the user mentors |
| `own_record` | The signed-in student's own record only |
| `system` | Platform administration objects; never student records |

## Field sets

| Field set | Fields |
|---|---|
| `student_core` | `student_id`, `name`, `department`, `year`, `programme`, `cohort_profile`, `dataset` |
| `student_master_all` | `student_id`, `name`, `department`, `year`, `programme`, `cohort_profile`, `dataset`, `email`, `date_of_birth`, `mentor_sub`, `mentor_name`, `status`, `version`, `updated_at`, `updated_by` |
| `insight_all` | `student_id`, `name`, `department`, `year`, `dataset`, `period`, `score`, `indicative_score`, `status`, `band`, `coverage`, `profile`, `components`, `risks`, `segments`, `support_needs`, `eligibility`, `trend`, `by_period`, `score_rows`, `indicators`, `sources`, `summary`, `scoring_version`, `calculated_at`, `recalc_status`, `mentor_name` |
| `insight_student_view` | `student_id`, `name`, `department`, `year`, `dataset`, `period`, `score`, `indicative_score`, `status`, `band`, `coverage`, `profile`, `components`, `risks`, `segments`, `trend`, `by_period`, `score_rows`, `sources`, `indicators`, `summary`, `scoring_version`, `calculated_at`, `recalc_status`, `mentor_name` |
| `insight_placement` | `student_id`, `name`, `department`, `year`, `dataset`, `period`, `profile`, `components.placement`, `components.skills`, `risks.placement`, `eligibility`, `segments`, `scoring_version`, `calculated_at`, `recalc_status` |
| `insight_activity` | `student_id`, `name`, `department`, `year`, `dataset`, `period`, `components.engagement`, `calculated_at`, `recalc_status` |
| `intervention_all` | `*` |
| `intervention_student_view` | `intervention_id`, `student_id`, `title`, `category`, `status`, `due_date`, `review_date`, `outcome`, `created_at` |
| `record_all` | `*` |
| `student_self` | `student_id`, `name`, `department`, `year`, `programme`, `cohort_profile`, `dataset`, `email`, `date_of_birth`, `mentor_name`, `status` |

## College Administrator (`college_admin`)

Manages student master records, imports, mentor assignments and the approved scoring configuration; sees college-wide dashboards and reviews interventions.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read, create, update | `college` | `student_master_all` |
| `student_insight` | read | `college` | `insight_all` |
| `record.academic_result` | read, create, update | `college` | `record_all` |
| `record.marks` | read | `college` | `record_all` |
| `record.attendance` | read | `college` | `record_all` |
| `record.lms` | read | `college` | `record_all` |
| `record.engagement` | read | `college` | `record_all` |
| `record.certification` | read | `college` | `record_all` |
| `record.placement_assessment` | read | `college` | `record_all` |
| `record.skills` | read | `college` | `record_all` |
| `record.feedback` | read | `college` | `record_all` |
| `import` | create, read | `college` | `record_all` |
| `mentor_assignment` | read, assign | `college` | `record_all` |
| `correction` | read | `college` | `record_all` |
| `intervention` | read, update | `college` | `intervention_all` |
| `note.staff` | read, create | `college` | `record_all` |
| `note.confidential` | read | `college` | `record_all` |
| `scoring_config` | read, propose, activate | `college` | `record_all` |
| `insight` | recompute | `college` | `record_all` |
| `audit.academic` | read | `college` | `record_all` |
| `role_matrix` | read | `college` | `record_all` |

## Head of Department (`hod`)

Sees their department, assigns department mentors, approves corrections within the department and monitors department interventions.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read | `department` | `student_master_all` |
| `student_insight` | read | `department` | `insight_all` |
| `record.academic_result` | read | `department` | `record_all` |
| `record.marks` | read | `department` | `record_all` |
| `record.attendance` | read | `department` | `record_all` |
| `record.lms` | read | `department` | `record_all` |
| `record.engagement` | read | `department` | `record_all` |
| `record.certification` | read | `department` | `record_all` |
| `record.placement_assessment` | read | `department` | `record_all` |
| `record.skills` | read | `department` | `record_all` |
| `record.feedback` | read | `department` | `record_all` |
| `mentor_assignment` | read, assign | `department` | `record_all` |
| `correction` | read, approve | `department` | `record_all` |
| `intervention` | read | `department` | `intervention_all` |
| `note.staff` | read, create | `department` | `record_all` |
| `note.confidential` | read | `department` | `record_all` |
| `role_matrix` | read | `department` | `record_all` |

## Faculty / Mentor (`mentor`)

Enters marks and attendance only for assigned subjects and students, enters LMS and assessment summaries, sees authorised insights and manages assigned interventions.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read | `assigned_students` | `student_master_all` |
| `student_master` | read | `assigned_subject` | `student_core` |
| `student_insight` | read | `assigned_students` | `insight_all` |
| `record.marks` | read, create, update | `assigned_subject` | `record_all` |
| `record.attendance` | read, create, update | `assigned_subject` | `record_all` |
| `record.marks` | read | `assigned_students` | `record_all` |
| `record.attendance` | read | `assigned_students` | `record_all` |
| `record.academic_result` | read | `assigned_students` | `record_all` |
| `record.lms` | read, create, update | `assigned_students` | `record_all` |
| `record.engagement` | read | `assigned_students` | `record_all` |
| `record.certification` | read | `assigned_students` | `record_all` |
| `record.placement_assessment` | read | `assigned_students` | `record_all` |
| `record.skills` | read | `assigned_students` | `record_all` |
| `record.feedback` | read | `assigned_students` | `record_all` |
| `import` | create, read | `assigned_subject` | `record_all` |
| `correction` | read | `assigned_subject` | `record_all` |
| `intervention` | read, create, update | `assigned_students` | `intervention_all` |
| `note.staff` | read, create | `assigned_students` | `record_all` |
| `note.confidential` | read, create | `assigned_students` | `record_all` |
| `role_matrix` | read | `assigned_students` | `record_all` |

## Placement Officer (`placement_officer`)

Enters aptitude, coding, interview and readiness results, maintains skill assessments and assigns placement training; sees only the student fields needed for this.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read | `college` | `student_core` |
| `student_insight` | read | `college` | `insight_placement` |
| `record.placement_assessment` | read, create, update | `college` | `record_all` |
| `record.skills` | read, create, update | `college` | `record_all` |
| `import` | create, read | `college` | `record_all` |
| `intervention` | read, create, update | `college` | `intervention_all` |
| `note.staff` | read, create | `college` | `record_all` |
| `role_matrix` | read | `college` | `record_all` |

Constraints: `intervention_categories` = placement_training

## Activity Coordinator (`activity_coordinator`)

Maintains events and participation and verifies engagement and certification submissions. Cannot modify academic or placement results.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read | `college` | `student_core` |
| `student_insight` | read | `college` | `insight_activity` |
| `record.engagement` | read, create, update, verify | `college` | `record_all` |
| `record.certification` | read, verify | `college` | `record_all` |
| `import` | create, read | `college` | `record_all` |
| `role_matrix` | read | `college` | `record_all` |

## Student (`student`)

Sees their own authorised profile, scores and recommendations; submits feedback and certifications. Cannot edit verified results or calculated scores, and never sees staff notes.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `student_master` | read | `own_record` | `student_self` |
| `student_insight` | read | `own_record` | `insight_student_view` |
| `record.academic_result` | read | `own_record` | `record_all` |
| `record.marks` | read | `own_record` | `record_all` |
| `record.attendance` | read | `own_record` | `record_all` |
| `record.lms` | read | `own_record` | `record_all` |
| `record.engagement` | read | `own_record` | `record_all` |
| `record.certification` | read, submit | `own_record` | `record_all` |
| `record.placement_assessment` | read | `own_record` | `record_all` |
| `record.skills` | read | `own_record` | `record_all` |
| `record.feedback` | read, submit | `own_record` | `record_all` |
| `intervention` | read | `own_record` | `intervention_student_view` |
| `role_matrix` | read | `own_record` | `record_all` |

## System Administrator (`system_admin`)

Manages accounts, role assignments and technical configuration. Has no access to student records and cannot change their own role assignments.

| Resource | Action | Scope | Fields |
|---|---|---|---|
| `user_account` | read, create, update | `system` | `record_all` |
| `role_assignment` | assign | `system` | `record_all` |
| `system_config` | read, update | `system` | `record_all` |
| `audit.technical` | read | `system` | `record_all` |
| `role_matrix` | read | `system` | `record_all` |

## Separation of duties

- No account may hold system_admin together with any student-data role.
- Nobody may add or remove their own role assignments.
- Only system_admin may create accounts or change role assignments.
