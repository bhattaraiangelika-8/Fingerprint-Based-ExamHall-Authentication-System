"""
Data Structures for Seat Auto-Mapping
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StudentInfo:
    """Student data for seat mapping."""
    id: int
    name: str
    roll_number: str
    subject_code: str
    special_needs: bool = False
    gender: str = ''


@dataclass
class HallInfo:
    """Hall layout data for seat mapping."""
    id: int
    name: str
    center_id: int
    rows: int
    columns: int
    total_capacity: int


@dataclass
class SeatAssignmentInfo:
    """A single seat assignment."""
    student_id: int
    hall_id: int
    row: int
    col: int
    seat_label: str
    subject_code: str = ''


class SeatGrid:
    """Represents a hall's seat grid."""

    def __init__(self, rows: int, columns: int, hall_id: int):
        self.rows = rows
        self.columns = columns
        self.hall_id = hall_id
        self.grid = [[None for _ in range(columns)] for _ in range(rows)]

    def is_occupied(self, row: int, col: int) -> bool:
        if row < 0 or row >= self.rows or col < 0 or col >= self.columns:
            return True  # Out of bounds treated as occupied
        return self.grid[row][col] is not None

    def assign(self, row: int, col: int, student: StudentInfo):
        if not self.is_occupied(row, col):
            self.grid[row][col] = student

    def get_student(self, row: int, col: int) -> Optional[StudentInfo]:
        if 0 <= row < self.rows and 0 <= col < self.columns:
            return self.grid[row][col]
        return None

    def get_neighbor_subjects(self, row: int, col: int) -> set:
        """Get set of subject codes of 4-directional neighbors."""
        subjects = set()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            neighbor = self.get_student(nr, nc)
            if neighbor:
                subjects.add(neighbor.subject_code)
        return subjects

    def get_all_assignments(self) -> List[SeatAssignmentInfo]:
        """Get all assignments as flat list."""
        result = []
        for r in range(self.rows):
            for c in range(self.columns):
                student = self.grid[r][c]
                if student:
                    seat_label = f"{chr(65 + r)}{c + 1}"
                    result.append(SeatAssignmentInfo(
                        student_id=student.id,
                        hall_id=self.hall_id,
                        row=r,
                        col=c,
                        seat_label=seat_label,
                        subject_code=student.subject_code,
                    ))
        return result

    def find_empty_seat(self, start_row=0, start_col=0):
        """Find next empty seat from given position."""
        for r in range(start_row, self.rows):
            start_c = start_col if r == start_row else 0
            for c in range(start_c, self.columns):
                if not self.is_occupied(r, c):
                    return r, c
        return None, None
