/** Display labels shared by pages. Keys match the API. */
export const SEGMENTS: Record<string, string> = {
  strong_academics_low_placement: 'Strong academics, low placement readiness',
  declining_attendance_results: 'Declining attendance and results',
  strong_skills_academic_support: 'Strong skills, academic support required',
  improving_after_intervention: 'Improving after intervention',
  consistently_performing_well: 'Consistently performing well',
  insufficient_data: 'Insufficient data',
};
export const COMPONENTS: Record<string, string> = {
  academic: 'Academic', attendance: 'Attendance', lms: 'LMS activity', placement: 'Placement readiness',
  skills: 'Skills', engagement: 'Engagement',
};
export const ROLES: Record<string, string> = {
  college_admin: 'College Administrator', hod: 'Head of Department', mentor: 'Faculty / Mentor',
  placement_officer: 'Placement Officer', activity_coordinator: 'Activity Coordinator', student: 'Student',
  system_admin: 'System Administrator',
};
export const IV_CATEGORIES: Record<string, string> = {
  academic: 'Academic', attendance: 'Attendance', wellbeing: 'Wellbeing', placement_training: 'Placement training', other: 'Other',
};
export const OUTCOMES: Record<string, string> = {
  improved: 'Improved', no_change: 'No change', declined: 'Declined', not_assessed: 'Not assessed',
};
export function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return isNaN(+d) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
export function pct(v?: number | null): string {
  return v === null || v === undefined ? '–' : `${Math.round(v * 100)}%`;
}
/** Download text as a file (CSV templates and exports). */
export function download(name: string, text: string, type = 'text/csv'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
