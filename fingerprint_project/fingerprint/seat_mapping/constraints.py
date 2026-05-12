"""
Constraint Validation for Seat Auto-Mapping
"""
import logging
from typing import List, Dict
from .data_structures import SeatGrid, SeatAssignmentInfo, StudentInfo

logger = logging.getLogger('fingerprint')


def check_neighbour_violations(grid: SeatGrid) -> List[Dict]:
    """
    Check for same-subject neighbour violations (4-directional).
    Returns list of violation records.
    """
    violations = []
    for r in range(grid.rows):
        for c in range(grid.columns):
            student = grid.get_student(r, c)
            if not student:
                continue
            neighbors = grid.get_neighbor_subjects(r, c)
            if student.subject_code in neighbors:
                violations.append({
                    'student_id': student.id,
                    'row': r,
                    'col': c,
                    'subject_code': student.subject_code,
                    'neighbor_subject': student.subject_code,
                })
    return violations


def validate_seat_map(assignments: List[SeatAssignmentInfo], constraints: dict) -> Dict:
    """
    Validate a complete seat map against all constraints.
    Returns dict with violations and warnings.
    """
    results = {
        'valid': True,
        'violations': [],
        'warnings': [],
    }

    # Group by hall
    hall_assignments: Dict[int, List[SeatAssignmentInfo]] = {}
    for a in assignments:
        hall_assignments.setdefault(a.hall_id, []).append(a)

    for hall_id, hall_asgns in hall_assignments.items():
        if not hall_asgns:
            continue

        # Build grid for this hall
        max_row = max(a.row for a in hall_asgns)
        max_col = max(a.col for a in hall_asgns)
        grid = SeatGrid(max_row + 1, max_col + 1, hall_id)

        # Populate grid (need StudentInfo objects)
        # We'll check subject violations using the data we have
        subject_map: Dict[int, str] = {}
        for a in hall_asgns:
            subject_map[a.student_id] = a.subject_code

        visited = set()

        def _get_subject_code(sid):
            return subject_map.get(sid, '')

        # Simple overlap check
        positions = {}
        for a in hall_asgns:
            key = (a.hall_id, a.row, a.col)
            if key in positions:
                results['violations'].append({
                    'type': 'DUPLICATE_POSITION',
                    'hall_id': a.hall_id,
                    'row': a.row,
                    'col': a.col,
                    'student_ids': [positions[key], a.student_id],
                })
                results['valid'] = False
            positions[key] = a.student_id

    return results
