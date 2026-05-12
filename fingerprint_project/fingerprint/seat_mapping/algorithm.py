"""
Seat Auto-Mapping Algorithm (Section 2.5 / Section 6)

Interleaves students by subject and assigns seats with constraint validation.
"""
import logging
from collections import defaultdict
from dataclasses import asdict
from typing import List, Dict, Any

from .data_structures import StudentInfo, HallInfo, SeatGrid, SeatAssignmentInfo
from .constraints import check_neighbour_violations

logger = logging.getLogger('fingerprint')

MAX_ITERATIONS = 50


def generate_seat_map(students: list, halls: list, constraints: dict = None) -> Dict[str, Any]:
    """
    Main entry point. Generates a seat map for an exam.

    Args:
        students: List of StudentInfo dataclass objects
        halls: List of HallInfo dataclass objects
        constraints: Dict of constraint flags

    Returns:
        dict with 'assignments' (per-hall) and 'warnings'
    """
    if constraints is None:
        constraints = {}

    student_infos = students
    hall_infos = halls

    result = {'assignments': {}, 'warnings': []}

    # Step 1: Separate special needs students
    special_needs = [s for s in student_infos if s.special_needs]
    regular = [s for s in student_infos if not s.special_needs]

    # Step 2: Group by subject
    groups = defaultdict(list)
    for s in regular:
        groups[s.subject_code].append(s)
    for s in special_needs:
        groups[s.subject_code].append(s)

    # Step 3: Round-robin interleave
    interleaved = _round_robin_merge(dict(groups))

    # Step 4: Distribute across halls
    hall_assignments = _distribute_to_halls(interleaved, hall_infos, constraints.get('reserve_buffer', True))

    # Step 5: Map to seat grid per hall
    for hall_id, hall_students in hall_assignments.items():
        hall_info = next((h for h in hall_infos if h.id == hall_id), None)
        if not hall_info:
            continue

        grid = SeatGrid(hall_info.rows, hall_info.columns, hall_id)

        # Assign special needs first (front rows)
        sn_in_hall = [s for s in hall_students if s.special_needs]
        regular_in_hall = [s for s in hall_students if not s.special_needs]

        _assign_to_grid(grid, sn_in_hall, front_rows=True)
        _assign_to_grid(grid, regular_in_hall)

        # Step 6: Validate constraints
        violations = check_neighbour_violations(grid)
        iterations = 0

        while violations and iterations < MAX_ITERATIONS:
            _resolve_violations(grid, violations)
            violations = check_neighbour_violations(grid)
            iterations += 1

        if violations:
            result['warnings'].append(
                f"Hall {hall_id}: Could not resolve {len(violations)} constraint violations — manual review needed"
            )

        result['assignments'][hall_id] = [asdict(a) if hasattr(a, '__dataclass_fields__') else {
            'student_id': a.student_id,
            'hall_id': a.hall_id,
            'row': a.row,
            'col': a.col,
            'seat_label': a.seat_label,
        } for a in grid.get_all_assignments()]

    logger.info(
        "Seat map generated: %d halls, %d students assigned",
        len(result['assignments']), sum(len(v) for v in result['assignments'].values())
    )

    return result


# ── Helper functions ──


def _build_student_infos(students) -> List[StudentInfo]:
    """Convert Django Student objects to StudentInfo dataclasses."""
    infos = []
    for s in students:
        subjects = list(s.subjects.all())
        subject_code = subjects[0].code if subjects else ''
        infos.append(StudentInfo(
            id=s.student_id,
            name=s.full_name,
            roll_number=s.registration_no,
            subject_code=subject_code,
            special_needs=getattr(s, 'special_needs', False),
            gender=getattr(s, 'gender', ''),
        ))
    return infos


def _build_hall_infos(halls) -> List[HallInfo]:
    """Convert Django Hall objects to HallInfo dataclasses."""
    return [
        HallInfo(id=h.hall_id, name=h.name, center_id=h.center_id,
                 rows=h.rows, columns=h.columns, total_capacity=h.total_capacity)
        for h in halls
    ]


def _round_robin_merge(groups: Dict[str, list]) -> list:
    """
    Interleave students from different subject groups round-robin style.
    Ensures adjacent students (in the linear list) tend to be from different subjects.
    """
    if not groups:
        return []

    # Sort keys for deterministic behavior
    keys = sorted(groups.keys())
    group_lists = {k: list(v) for k, v in groups.items()}
    indices = {k: 0 for k in keys}
    result = []
    total = sum(len(v) for v in group_lists.values())

    # Shuffle the order in which groups are picked each round
    import random
    rng = random.Random(42)  # deterministic seed

    while len(result) < total:
        rng.shuffle(keys)
        for k in keys:
            if indices[k] < len(group_lists[k]):
                result.append(group_lists[k][indices[k]])
                indices[k] += 1
                if len(result) == total:
                    break

    return result


def _distribute_to_halls(students: List[StudentInfo], halls: List[HallInfo], reserve_buffer: bool = True) -> Dict[int, list]:
    """
    Distribute students across halls by capacity.
    Reserves the last row of each hall as buffer if reserve_buffer is True.
    """
    assignments: Dict[int, list] = {h.id: [] for h in halls}
    hall_map = {h.id: h for h in halls}

    # Calculate effective capacity (exclude buffer row)
    effective_caps = {}
    total_capacity = 0
    for h in halls:
        buffer_rows = 1 if reserve_buffer else 0
        effective_rows = max(0, h.rows - buffer_rows)
        effective_caps[h.id] = effective_rows * h.columns
        total_capacity += effective_caps[h.id]

    if not total_capacity:
        return assignments

    # Distribute proportionally
    idx = 0
    for hall_id in sorted(assignments.keys()):
        cap = effective_caps.get(hall_id, 0)
        hall_students = students[idx:idx + cap]
        assignments[hall_id] = hall_students
        idx += cap
        if idx >= len(students):
            break

    return assignments


def _assign_to_grid(grid: SeatGrid, students: List[StudentInfo], front_rows: bool = False):
    """Assign students to grid positions row by row."""
    if front_rows:
        # Special needs only get front row (row 0)
        for r in range(1):
            for c in range(grid.columns):
                if not students:
                    return
                student = students.pop(0)
                grid.grid[r][c] = student
    else:
        # Fill any empty cells in row 0 first (leftover from special needs), then rows 1+
        for r in range(grid.rows):
            for c in range(grid.columns):
                if grid.grid[r][c] is not None:
                    continue
                if not students:
                    return
                student = students.pop(0)
                grid.grid[r][c] = student


def _resolve_violations(grid: SeatGrid, violations: list):
    """
    Attempt to resolve neighbour violations by swapping violating
    student with a nearby student from a different subject.
    """
    swapped = set()

    for v in violations:
        student_id = v['student_id']
        r, c = v['row'], v['col']
        subject_code = v['subject_code']

        if student_id in swapped:
            continue

        # Search for a swap candidate nearby
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                candidate = grid.get_student(nr, nc)
                if candidate and candidate.subject_code != subject_code:
                    candidate_id = candidate.id
                    if candidate_id in swapped:
                        continue

                    # Check if swap would fix both sides
                    current_neighbors = grid.get_neighbor_subjects(r, c)
                    candidate_neighbors = grid.get_neighbor_subjects(nr, nc)

                    # Get the actual student objects
                    current = grid.get_student(r, c)
                    cand = grid.get_student(nr, nc)

                    if current and cand:
                        # Swap
                        grid.grid[r][c] = cand
                        grid.grid[nr][nc] = current
                        swapped.add(student_id)
                        swapped.add(candidate_id)
                        break
            else:
                continue
            break
