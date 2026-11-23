"""Deterministic synthetic university relational dataset (18 operational tables).

Produces both PostgreSQL seed SQL (`db/seed.sql`) and a SQLite mirror (`data/university.db`)
so that Phase 1 SQL queries, schema metrics, and test assertions run cleanly anywhere.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def build_dataset() -> dict[str, list[dict[str, Any]]]:
    """Return canonical deterministic rows for all 18 operational tables."""
    departments = [
        {"dept_code": "CS", "dept_name": "Computer Science", "dean_name": "Dr. Elena Vance", "building": "Turing Hall", "annual_grant_pool": 480000.00},
        {"dept_code": "ECE", "dept_name": "Electrical & Computer Engineering", "dean_name": "Dr. Marcus Sterling", "building": "Maxwell Center", "annual_grant_pool": 410000.00},
        {"dept_code": "BIO", "dept_name": "Biological Sciences", "dean_name": "Dr. Priya Nair", "building": "Franklin Pavilion", "annual_grant_pool": 360000.00},
        {"dept_code": "MATH", "dept_name": "Applied Mathematics", "dean_name": "Dr. Henrik Lindqvist", "building": "Euler Hall", "annual_grant_pool": 220000.00},
        {"dept_code": "ECON", "dept_name": "Economics & Policy", "dean_name": "Dr. Claire Beaumont", "building": "Keynes Commons", "annual_grant_pool": 195000.00},
        {"dept_code": "ME", "dept_name": "Mechanical Engineering", "dean_name": "Dr. Kenji Takahashi", "building": "Watt Wing", "annual_grant_pool": 340000.00},
    ]

    # Note real GPA ambiguity: cumulative_gpa vs semester_gpa diverge deliberately on key personas!
    students = [
        {"student_id": "STU-1001", "full_name": "Maya Lin", "email": "maya.lin@alderwood.edu", "dept_code": "CS", "year_of_study": 3, "cumulative_gpa": 3.74, "semester_gpa": 3.42, "advisor_name": "Dr. Aris Thorne", "enrollment_status": "active", "residency_status": "in_state"},
        {"student_id": "STU-1002", "full_name": "Liam O'Connor", "email": "liam.oconnor@alderwood.edu", "dept_code": "CS", "year_of_study": 3, "cumulative_gpa": 3.38, "semester_gpa": 3.85, "advisor_name": "Dr. Nadia Patel", "enrollment_status": "active", "residency_status": "out_of_state"},
        {"student_id": "STU-1003", "full_name": "Sofia Alvarez", "email": "sofia.alvarez@alderwood.edu", "dept_code": "ECE", "year_of_study": 4, "cumulative_gpa": 3.89, "semester_gpa": 3.94, "advisor_name": "Dr. David Kim", "enrollment_status": "active", "residency_status": "international"},
        {"student_id": "STU-1004", "full_name": "Noah Brooks", "email": "noah.brooks@alderwood.edu", "dept_code": "BIO", "year_of_study": 2, "cumulative_gpa": 3.61, "semester_gpa": 3.55, "advisor_name": "Dr. Grace Chen", "enrollment_status": "active", "residency_status": "in_state"},
        {"student_id": "STU-1005", "full_name": "Aarav Mehta", "email": "aarav.mehta@alderwood.edu", "dept_code": "CS", "year_of_study": 1, "cumulative_gpa": 3.92, "semester_gpa": 3.92, "advisor_name": "Dr. Aris Thorne", "enrollment_status": "active", "residency_status": "international"},
        {"student_id": "STU-1006", "full_name": "Chloe Dubois", "email": "chloe.dubois@alderwood.edu", "dept_code": "ECON", "year_of_study": 3, "cumulative_gpa": 3.45, "semester_gpa": 3.10, "advisor_name": "Dr. Julian Mercer", "enrollment_status": "active", "residency_status": "out_of_state"},
        {"student_id": "STU-1007", "full_name": "Ethan Wright", "email": "ethan.wright@alderwood.edu", "dept_code": "ME", "year_of_study": 4, "cumulative_gpa": 3.52, "semester_gpa": 3.78, "advisor_name": "Dr. Hannah Sato", "enrollment_status": "active", "residency_status": "in_state"},
        {"student_id": "STU-1008", "full_name": "Zara Hassan", "email": "zara.hassan@alderwood.edu", "dept_code": "MATH", "year_of_study": 2, "cumulative_gpa": 3.81, "semester_gpa": 3.65, "advisor_name": "Dr. Henrik Lindqvist", "enrollment_status": "active", "residency_status": "in_state"},
        {"student_id": "STU-1009", "full_name": "Lucas Moreau", "email": "lucas.moreau@alderwood.edu", "dept_code": "CS", "year_of_study": 4, "cumulative_gpa": 3.18, "semester_gpa": 3.62, "advisor_name": "Dr. Nadia Patel", "enrollment_status": "active", "residency_status": "out_of_state"},
        {"student_id": "STU-1010", "full_name": "Hannah Kim", "email": "hannah.kim@alderwood.edu", "dept_code": "ECE", "year_of_study": 2, "cumulative_gpa": 3.56, "semester_gpa": 3.49, "advisor_name": "Dr. David Kim", "enrollment_status": "active", "residency_status": "in_state"},
        {"student_id": "STU-1011", "full_name": "Mateo Rossi", "email": "mateo.rossi@alderwood.edu", "dept_code": "BIO", "year_of_study": 3, "cumulative_gpa": 3.29, "semester_gpa": 2.95, "advisor_name": "Dr. Grace Chen", "enrollment_status": "probation_watch", "residency_status": "in_state"},
        {"student_id": "STU-1012", "full_name": "Amara Okafor", "email": "amara.okafor@alderwood.edu", "dept_code": "CS", "year_of_study": 2, "cumulative_gpa": 3.67, "semester_gpa": 3.71, "advisor_name": "Dr. Aris Thorne", "enrollment_status": "active", "residency_status": "international"},
    ]

    courses = [
        {"course_id": "CS-301", "dept_code": "CS", "title": "Algorithms and Complexity", "credits": 4, "course_level": 300, "instructor_name": "Dr. Aris Thorne", "max_capacity": 90},
        {"course_id": "CS-340", "dept_code": "CS", "title": "Machine Learning Foundations", "credits": 4, "course_level": 300, "instructor_name": "Dr. Nadia Patel", "max_capacity": 75},
        {"course_id": "CS-410", "dept_code": "CS", "title": "Distributed Systems", "credits": 4, "course_level": 400, "instructor_name": "Dr. Elena Vance", "max_capacity": 60},
        {"course_id": "ECE-310", "dept_code": "ECE", "title": "Embedded Microarchitecture", "credits": 4, "course_level": 300, "instructor_name": "Dr. David Kim", "max_capacity": 55},
        {"course_id": "ECE-420", "dept_code": "ECE", "title": "Photonics and Signal Processing", "credits": 3, "course_level": 400, "instructor_name": "Dr. Marcus Sterling", "max_capacity": 40},
        {"course_id": "BIO-215", "dept_code": "BIO", "title": "Molecular Genetics Lab", "credits": 4, "course_level": 200, "instructor_name": "Dr. Grace Chen", "max_capacity": 48},
        {"course_id": "MATH-240", "dept_code": "MATH", "title": "Linear Optimization", "credits": 3, "course_level": 200, "instructor_name": "Dr. Henrik Lindqvist", "max_capacity": 70},
        {"course_id": "ECON-305", "dept_code": "ECON", "title": "Econometric Methods", "credits": 3, "course_level": 300, "instructor_name": "Dr. Julian Mercer", "max_capacity": 65},
        {"course_id": "ME-380", "dept_code": "ME", "title": "Thermodynamics and Propulsion", "credits": 4, "course_level": 300, "instructor_name": "Dr. Hannah Sato", "max_capacity": 50},
    ]

    enrollments = [
        {"enrollment_id": "ENR-001", "student_id": "STU-1001", "course_id": "CS-301", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-002", "student_id": "STU-1001", "course_id": "CS-340", "term": "Fall 2026", "grade_points": 3.30, "letter_grade": "B+", "status": "enrolled"},
        {"enrollment_id": "ENR-003", "student_id": "STU-1001", "course_id": "MATH-240", "term": "Fall 2026", "grade_points": 3.30, "letter_grade": "B+", "status": "enrolled"},
        {"enrollment_id": "ENR-004", "student_id": "STU-1002", "course_id": "CS-301", "term": "Fall 2026", "grade_points": 4.00, "letter_grade": "A", "status": "enrolled"},
        {"enrollment_id": "ENR-005", "student_id": "STU-1002", "course_id": "CS-340", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-006", "student_id": "STU-1003", "course_id": "ECE-420", "term": "Fall 2026", "grade_points": 4.00, "letter_grade": "A", "status": "enrolled"},
        {"enrollment_id": "ENR-007", "student_id": "STU-1003", "course_id": "CS-410", "term": "Fall 2026", "grade_points": 3.90, "letter_grade": "A", "status": "enrolled"},
        {"enrollment_id": "ENR-008", "student_id": "STU-1004", "course_id": "BIO-215", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-009", "student_id": "STU-1006", "course_id": "ECON-305", "term": "Fall 2026", "grade_points": 3.00, "letter_grade": "B", "status": "enrolled"},
        {"enrollment_id": "ENR-010", "student_id": "STU-1007", "course_id": "ME-380", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-011", "student_id": "STU-1008", "course_id": "MATH-240", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-012", "student_id": "STU-1009", "course_id": "CS-410", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
        {"enrollment_id": "ENR-013", "student_id": "STU-1010", "course_id": "ECE-310", "term": "Fall 2026", "grade_points": 3.30, "letter_grade": "B+", "status": "enrolled"},
        {"enrollment_id": "ENR-014", "student_id": "STU-1011", "course_id": "BIO-215", "term": "Fall 2026", "grade_points": 3.00, "letter_grade": "B", "status": "enrolled"},
        {"enrollment_id": "ENR-015", "student_id": "STU-1012", "course_id": "CS-301", "term": "Fall 2026", "grade_points": 3.70, "letter_grade": "A-", "status": "enrolled"},
    ]

    # Note: GR-CS-01 has an intentional DB (2026-12-15) vs PDF v2.0 (2026-12-01) conflict!
    # Note: GR-GEN-04 is intentionally EXPIRED (2026-06-30 < 2026-11-23).
    grants = [
        {"grant_id": "GR-CS-01", "grant_name": "Turing Undergraduate Research Fellowship", "dept_code": "CS", "min_gpa": 3.50, "min_year": 2, "max_year": 4, "award_amount": 5500.00, "deadline": "2026-12-15", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-CS-02", "grant_name": "Alderwood AI Systems Innovation Stipend", "dept_code": "CS", "min_gpa": 3.25, "min_year": 3, "max_year": 4, "award_amount": 4000.00, "deadline": "2026-12-20", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-CS-03", "grant_name": "First-Year Computing Discovery Award", "dept_code": "CS", "min_gpa": 3.60, "min_year": 1, "max_year": 2, "award_amount": 2500.00, "deadline": "2027-01-15", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-ECE-01", "grant_name": "Maxwell Hardware Prototyping Grant", "dept_code": "ECE", "min_gpa": 3.40, "min_year": 2, "max_year": 4, "award_amount": 4800.00, "deadline": "2026-12-10", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-BIO-01", "grant_name": "Franklin Genomics Fieldwork Grant", "dept_code": "BIO", "min_gpa": 3.30, "min_year": 2, "max_year": 4, "award_amount": 4200.00, "deadline": "2026-12-18", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-ME-01", "grant_name": "Watt Sustainable Robotics Fellowship", "dept_code": "ME", "min_gpa": 3.35, "min_year": 3, "max_year": 4, "award_amount": 5000.00, "deadline": "2027-01-10", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-GEN-01", "grant_name": "Provost Cross-Disciplinary Research Grant", "dept_code": "ALL", "min_gpa": 3.50, "min_year": 2, "max_year": 4, "award_amount": 3500.00, "deadline": "2026-12-30", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-GEN-02", "grant_name": "Alderwood Student Conference Travel Fund", "dept_code": "ALL", "min_gpa": 3.00, "min_year": 1, "max_year": 4, "award_amount": 1200.00, "deadline": "2027-02-01", "status": "open", "funding_cycle": "Spring 2027"},
        {"grant_id": "GR-GEN-04", "grant_name": "Summer 2026 Heritage Innovation Grant", "dept_code": "ALL", "min_gpa": 3.20, "min_year": 2, "max_year": 4, "award_amount": 3000.00, "deadline": "2026-06-30", "status": "expired", "funding_cycle": "Summer 2026"},
    ]

    fee_ledger = [
        {"ledger_id": "LED-2026-001", "student_id": "STU-1001", "term": "Fall 2026", "category": "Tuition & Lab", "amount_due": 7450.00, "amount_paid": 7450.00, "due_date": "2026-09-15", "status": "paid"},
        {"ledger_id": "LED-2026-002", "student_id": "STU-1002", "term": "Fall 2026", "category": "Out-of-State Tuition", "amount_due": 14800.00, "amount_paid": 12000.00, "due_date": "2026-12-05", "status": "partial"},
        {"ledger_id": "LED-2026-003", "student_id": "STU-1003", "term": "Fall 2026", "category": "International Tuition & Lab", "amount_due": 16200.00, "amount_paid": 16200.00, "due_date": "2026-09-15", "status": "paid"},
        {"ledger_id": "LED-2026-004", "student_id": "STU-1004", "term": "Fall 2026", "category": "Tuition & Lab", "amount_due": 7600.00, "amount_paid": 7600.00, "due_date": "2026-09-15", "status": "paid"},
        {"ledger_id": "LED-2026-005", "student_id": "STU-1006", "term": "Fall 2026", "category": "Out-of-State Tuition", "amount_due": 14200.00, "amount_paid": 10000.00, "due_date": "2026-11-30", "status": "unpaid_balance"},
        {"ledger_id": "LED-2026-006", "student_id": "STU-1009", "term": "Fall 2026", "category": "Out-of-State Tuition", "amount_due": 14800.00, "amount_paid": 14800.00, "due_date": "2026-09-15", "status": "paid"},
        {"ledger_id": "LED-2026-007", "student_id": "STU-1011", "term": "Fall 2026", "category": "Tuition & Lab", "amount_due": 7600.00, "amount_paid": 5000.00, "due_date": "2026-11-15", "status": "overdue"},
        {"ledger_id": "LED-2026-008", "student_id": "STU-1012", "term": "Fall 2026", "category": "International Tuition & Lab", "amount_due": 16150.00, "amount_paid": 16150.00, "due_date": "2026-09-15", "status": "paid"},
    ]

    timetable = [
        {"slot_id": "TT-01", "course_id": "CS-301", "term": "Fall 2026", "day_of_week": "Monday", "start_time": "09:30", "end_time": "10:45", "room": "TH-204", "building": "Turing Hall"},
        {"slot_id": "TT-02", "course_id": "CS-301", "term": "Fall 2026", "day_of_week": "Wednesday", "start_time": "09:30", "end_time": "10:45", "room": "TH-204", "building": "Turing Hall"},
        {"slot_id": "TT-03", "course_id": "CS-340", "term": "Fall 2026", "day_of_week": "Tuesday", "start_time": "13:00", "end_time": "14:15", "room": "TH-108", "building": "Turing Hall"},
        {"slot_id": "TT-04", "course_id": "CS-410", "term": "Fall 2026", "day_of_week": "Thursday", "start_time": "15:00", "end_time": "16:30", "room": "TH-310", "building": "Turing Hall"},
        {"slot_id": "TT-05", "course_id": "ECE-310", "term": "Fall 2026", "day_of_week": "Monday", "start_time": "11:00", "end_time": "12:15", "room": "MC-112", "building": "Maxwell Center"},
        {"slot_id": "TT-06", "course_id": "ECE-420", "term": "Fall 2026", "day_of_week": "Wednesday", "start_time": "14:00", "end_time": "15:15", "room": "MC-215", "building": "Maxwell Center"},
        {"slot_id": "TT-07", "course_id": "BIO-215", "term": "Fall 2026", "day_of_week": "Tuesday", "start_time": "10:00", "end_time": "12:00", "room": "FP-102", "building": "Franklin Pavilion"},
        {"slot_id": "TT-08", "course_id": "MATH-240", "term": "Fall 2026", "day_of_week": "Friday", "start_time": "10:00", "end_time": "11:30", "room": "EH-201", "building": "Euler Hall"},
        {"slot_id": "TT-09", "course_id": "ECON-305", "term": "Fall 2026", "day_of_week": "Thursday", "start_time": "11:00", "end_time": "12:15", "room": "KC-105", "building": "Keynes Commons"},
        {"slot_id": "TT-10", "course_id": "ME-380", "term": "Fall 2026", "day_of_week": "Wednesday", "start_time": "09:00", "end_time": "10:30", "room": "WW-118", "building": "Watt Wing"},
    ]

    grant_applications = [
        {"application_id": "APP-501", "grant_id": "GR-CS-01", "student_id": "STU-1001", "submitted_at": "2026-11-10", "decision_status": "under_review", "requested_amount": 5500.00},
        {"application_id": "APP-502", "grant_id": "GR-CS-02", "student_id": "STU-1002", "submitted_at": "2026-11-12", "decision_status": "pending_mentor_signature", "requested_amount": 4000.00},
        {"application_id": "APP-503", "grant_id": "GR-ECE-01", "student_id": "STU-1003", "submitted_at": "2026-11-05", "decision_status": "approved", "requested_amount": 4800.00},
        {"application_id": "APP-504", "grant_id": "GR-BIO-01", "student_id": "STU-1004", "submitted_at": "2026-11-08", "decision_status": "under_review", "requested_amount": 4200.00},
        {"application_id": "APP-505", "grant_id": "GR-GEN-02", "student_id": "STU-1007", "submitted_at": "2026-11-14", "decision_status": "approved", "requested_amount": 1200.00},
        {"application_id": "APP-506", "grant_id": "GR-GEN-04", "student_id": "STU-1009", "submitted_at": "2026-06-12", "decision_status": "closed_past_cycle", "requested_amount": 3000.00},
    ]

    grant_history = [
        {"history_id": "GH-2025-01", "grant_id": "GR-CS-01", "fiscal_year": 2025, "total_disbursed": 66000.00, "recipients_count": 12, "archived_deadline": "2025-12-10"},
        {"history_id": "GH-2025-02", "grant_id": "GR-CS-02", "fiscal_year": 2025, "total_disbursed": 40000.00, "recipients_count": 10, "archived_deadline": "2025-12-15"},
        {"history_id": "GH-2025-03", "grant_id": "GR-ECE-01", "fiscal_year": 2025, "total_disbursed": 38400.00, "recipients_count": 8, "archived_deadline": "2025-12-05"},
        {"history_id": "GH-2025-04", "grant_id": "GR-GEN-01", "fiscal_year": 2025, "total_disbursed": 52500.00, "recipients_count": 15, "archived_deadline": "2025-12-22"},
    ]

    grant_reviewers = [
        {"reviewer_id": "REV-01", "grant_id": "GR-CS-01", "faculty_name": "Dr. Aris Thorne", "dept_code": "CS", "review_round": "Round 1"},
        {"reviewer_id": "REV-02", "grant_id": "GR-CS-02", "faculty_name": "Dr. Nadia Patel", "dept_code": "CS", "review_round": "Round 1"},
        {"reviewer_id": "REV-03", "grant_id": "GR-ECE-01", "faculty_name": "Dr. David Kim", "dept_code": "ECE", "review_round": "Final"},
        {"reviewer_id": "REV-04", "grant_id": "GR-BIO-01", "faculty_name": "Dr. Grace Chen", "dept_code": "BIO", "review_round": "Round 1"},
    ]

    fees = [
        {"fee_schedule_id": "FS-CS-IN", "dept_code": "CS", "residency_status": "in_state", "term": "Fall 2026", "base_tuition": 6800.00, "lab_fee": 450.00, "health_fee": 200.00},
        {"fee_schedule_id": "FS-CS-OUT", "dept_code": "CS", "residency_status": "out_of_state", "term": "Fall 2026", "base_tuition": 14150.00, "lab_fee": 450.00, "health_fee": 200.00},
        {"fee_schedule_id": "FS-CS-INT", "dept_code": "CS", "residency_status": "international", "term": "Fall 2026", "base_tuition": 15500.00, "lab_fee": 450.00, "health_fee": 200.00},
        {"fee_schedule_id": "FS-ECE-INT", "dept_code": "ECE", "residency_status": "international", "term": "Fall 2026", "base_tuition": 15500.00, "lab_fee": 500.00, "health_fee": 200.00},
        {"fee_schedule_id": "FS-BIO-IN", "dept_code": "BIO", "residency_status": "in_state", "term": "Fall 2026", "base_tuition": 6800.00, "lab_fee": 600.00, "health_fee": 200.00},
        {"fee_schedule_id": "FS-ECON-OUT", "dept_code": "ECON", "residency_status": "out_of_state", "term": "Fall 2026", "base_tuition": 14000.00, "lab_fee": 0.00, "health_fee": 200.00},
    ]

    fee_waivers = [
        {"waiver_id": "WVR-01", "student_id": "STU-1001", "waiver_type": "Merit Lab Fee Waiver", "waiver_amount": 450.00, "term": "Fall 2026", "approved_by": "Bursar Office", "status": "approved"},
        {"waiver_id": "WVR-02", "student_id": "STU-1005", "waiver_type": "Dean Entrance Waiver", "waiver_amount": 2500.00, "term": "Fall 2026", "approved_by": "Dr. Elena Vance", "status": "approved"},
        {"waiver_id": "WVR-03", "student_id": "STU-1006", "waiver_type": "Hardship Partial Waiver", "waiver_amount": 1500.00, "term": "Fall 2026", "approved_by": "Financial Aid Committee", "status": "pending"},
    ]

    student_semester_gpas = [
        {"record_id": "SGPA-01", "student_id": "STU-1001", "term": "Spring 2026", "semester_gpa": 3.88, "credits_attempted": 16, "deans_list_flag": True},
        {"record_id": "SGPA-02", "student_id": "STU-1001", "term": "Fall 2026", "semester_gpa": 3.42, "credits_attempted": 15, "deans_list_flag": False},
        {"record_id": "SGPA-03", "student_id": "STU-1002", "term": "Spring 2026", "semester_gpa": 3.12, "credits_attempted": 15, "deans_list_flag": False},
        {"record_id": "SGPA-04", "student_id": "STU-1002", "term": "Fall 2026", "semester_gpa": 3.85, "credits_attempted": 16, "deans_list_flag": True},
        {"record_id": "SGPA-05", "student_id": "STU-1003", "term": "Fall 2026", "semester_gpa": 3.94, "credits_attempted": 15, "deans_list_flag": True},
        {"record_id": "SGPA-06", "student_id": "STU-1009", "term": "Fall 2026", "semester_gpa": 3.62, "credits_attempted": 12, "deans_list_flag": True},
        {"record_id": "SGPA-07", "student_id": "STU-1011", "term": "Fall 2026", "semester_gpa": 2.95, "credits_attempted": 15, "deans_list_flag": False},
    ]

    student_awards = [
        {"award_id": "AWD-01", "student_id": "STU-1003", "award_title": "Dean's Honors Hardware Medal", "awarded_term": "Spring 2026", "stipend_amount": 1000.00},
        {"award_id": "AWD-02", "student_id": "STU-1005", "award_title": "Freshman Olympiad Scholarship", "awarded_term": "Fall 2026", "stipend_amount": 3000.00},
        {"award_id": "AWD-03", "student_id": "STU-1008", "award_title": "Euler Problem-Solving Prize", "awarded_term": "Spring 2026", "stipend_amount": 750.00},
    ]

    faculty_mentors = [
        {"mentor_id": "MNT-01", "faculty_name": "Dr. Aris Thorne", "dept_code": "CS", "research_area": "Algorithms & Verification", "accepting_undergrads": True, "office_room": "TH-402"},
        {"mentor_id": "MNT-02", "faculty_name": "Dr. Nadia Patel", "dept_code": "CS", "research_area": "Trustworthy Machine Learning", "accepting_undergrads": True, "office_room": "TH-415"},
        {"mentor_id": "MNT-03", "faculty_name": "Dr. David Kim", "dept_code": "ECE", "research_area": "Edge Silicon & Embedded Systems", "accepting_undergrads": True, "office_room": "MC-308"},
        {"mentor_id": "MNT-04", "faculty_name": "Dr. Grace Chen", "dept_code": "BIO", "research_area": "CRISPR & Computational Genomics", "accepting_undergrads": True, "office_room": "FP-301"},
        {"mentor_id": "MNT-05", "faculty_name": "Dr. Hannah Sato", "dept_code": "ME", "research_area": "Autonomous Aerial Robotics", "accepting_undergrads": False, "office_room": "WW-210"},
    ]

    research_labs = [
        {"lab_id": "LAB-01", "lab_name": "Formal Systems & Verification Lab", "dept_code": "CS", "pi_name": "Dr. Aris Thorne", "building": "Turing Hall", "safety_clearance_required": False},
        {"lab_id": "LAB-02", "lab_name": "Applied Machine Intelligence Lab", "dept_code": "CS", "pi_name": "Dr. Nadia Patel", "building": "Turing Hall", "safety_clearance_required": False},
        {"lab_id": "LAB-03", "lab_name": "Cleanroom Silicon Prototyping Lab", "dept_code": "ECE", "pi_name": "Dr. David Kim", "building": "Maxwell Center", "safety_clearance_required": True},
        {"lab_id": "LAB-04", "lab_name": "Genomics Wet Lab B", "dept_code": "BIO", "pi_name": "Dr. Grace Chen", "building": "Franklin Pavilion", "safety_clearance_required": True},
        {"lab_id": "LAB-05", "lab_name": "Autonomous Propulsion & Wind Tunnel", "dept_code": "ME", "pi_name": "Dr. Hannah Sato", "building": "Watt Wing", "safety_clearance_required": True},
    ]

    academic_calendar = [
        {"event_id": "CAL-01", "term": "Fall 2026", "event_name": "Fall Classes Begin", "event_date": "2026-09-02", "category": "academic"},
        {"event_id": "CAL-02", "term": "Fall 2026", "event_name": "Add/Drop Deadline", "event_date": "2026-09-16", "category": "registration"},
        {"event_id": "CAL-03", "term": "Fall 2026", "event_name": "Thanksgiving Recess Begins", "event_date": "2026-11-25", "category": "holiday"},
        {"event_id": "CAL-04", "term": "Fall 2026", "event_name": "Final Examinations Week", "event_date": "2026-12-14", "category": "exams"},
        {"event_id": "CAL-05", "term": "Spring 2027", "event_name": "Spring Term Opens", "event_date": "2027-01-19", "category": "academic"},
    ]

    scholarships_archive = [
        {"archive_id": "ARC-01", "legacy_code": "LEG-CS-99", "title": "Dot-Com Pioneers Endowed Award", "discontinued_year": 2022, "old_min_gpa": 3.20},
        {"archive_id": "ARC-02", "legacy_code": "LEG-GEN-88", "title": "Millennium Campus Founders Stipend", "discontinued_year": 2021, "old_min_gpa": 3.00},
        {"archive_id": "ARC-03", "legacy_code": "LEG-BIO-77", "title": "Old Botany Field Fellowship", "discontinued_year": 2023, "old_min_gpa": 3.10},
    ]

    return {
        "departments": departments,
        "students": students,
        "courses": courses,
        "enrollments": enrollments,
        "grants": grants,
        "fee_ledger": fee_ledger,
        "timetable": timetable,
        "grant_applications": grant_applications,
        "grant_history": grant_history,
        "grant_reviewers": grant_reviewers,
        "fees": fees,
        "fee_waivers": fee_waivers,
        "student_semester_gpas": student_semester_gpas,
        "student_awards": student_awards,
        "faculty_mentors": faculty_mentors,
        "research_labs": research_labs,
        "academic_calendar": academic_calendar,
        "scholarships_archive": scholarships_archive,
    }


def _sql_literal(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def write_postgres_seed_sql(dataset: dict[str, list[dict[str, Any]]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "-- Alderwood University Hybrid RAG — Synthetic Seed Data (PostgreSQL 16)",
        "BEGIN;",
    ]
    for table_name, rows in dataset.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        col_list = ", ".join(cols)
        for row in rows:
            vals = ", ".join(_sql_literal(row[c]) for c in cols)
            lines.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({vals}) ON CONFLICT DO NOTHING;")
    lines.append("COMMIT;")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sqlite_mirror(dataset: dict[str, list[dict[str, Any]]], db_path: Path) -> None:
    """Create a local SQLite 3 database mirroring all 20 tables for offline Phase 1 verification."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE departments (dept_code TEXT PRIMARY KEY, dept_name TEXT NOT NULL, dean_name TEXT NOT NULL, building TEXT NOT NULL, annual_grant_pool REAL NOT NULL);
        CREATE TABLE students (student_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, dept_code TEXT NOT NULL, year_of_study INTEGER NOT NULL, cumulative_gpa REAL NOT NULL, semester_gpa REAL NOT NULL, advisor_name TEXT NOT NULL, enrollment_status TEXT NOT NULL, residency_status TEXT NOT NULL);
        CREATE TABLE courses (course_id TEXT PRIMARY KEY, dept_code TEXT NOT NULL, title TEXT NOT NULL, credits INTEGER NOT NULL, course_level INTEGER NOT NULL, instructor_name TEXT NOT NULL, max_capacity INTEGER NOT NULL);
        CREATE TABLE enrollments (enrollment_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, course_id TEXT NOT NULL, term TEXT NOT NULL, grade_points REAL, letter_grade TEXT, status TEXT NOT NULL);
        CREATE TABLE grants (grant_id TEXT PRIMARY KEY, grant_name TEXT NOT NULL, dept_code TEXT NOT NULL, min_gpa REAL NOT NULL, min_year INTEGER NOT NULL, max_year INTEGER NOT NULL, award_amount REAL NOT NULL, deadline TEXT NOT NULL, status TEXT NOT NULL, funding_cycle TEXT NOT NULL);
        CREATE TABLE fee_ledger (ledger_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, term TEXT NOT NULL, category TEXT NOT NULL, amount_due REAL NOT NULL, amount_paid REAL NOT NULL, due_date TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE timetable (slot_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, term TEXT NOT NULL, day_of_week TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT NOT NULL, building TEXT NOT NULL);
        CREATE TABLE grant_applications (application_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, student_id TEXT NOT NULL, submitted_at TEXT NOT NULL, decision_status TEXT NOT NULL, requested_amount REAL NOT NULL);
        CREATE TABLE grant_history (history_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, fiscal_year INTEGER NOT NULL, total_disbursed REAL NOT NULL, recipients_count INTEGER NOT NULL, archived_deadline TEXT NOT NULL);
        CREATE TABLE grant_reviewers (reviewer_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, faculty_name TEXT NOT NULL, dept_code TEXT NOT NULL, review_round TEXT NOT NULL);
        CREATE TABLE fees (fee_schedule_id TEXT PRIMARY KEY, dept_code TEXT NOT NULL, residency_status TEXT NOT NULL, term TEXT NOT NULL, base_tuition REAL NOT NULL, lab_fee REAL NOT NULL, health_fee REAL NOT NULL);
        CREATE TABLE fee_waivers (waiver_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, waiver_type TEXT NOT NULL, waiver_amount REAL NOT NULL, term TEXT NOT NULL, approved_by TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE student_semester_gpas (record_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, term TEXT NOT NULL, semester_gpa REAL NOT NULL, credits_attempted INTEGER NOT NULL, deans_list_flag INTEGER NOT NULL);
        CREATE TABLE student_awards (award_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, award_title TEXT NOT NULL, awarded_term TEXT NOT NULL, stipend_amount REAL NOT NULL);
        CREATE TABLE faculty_mentors (mentor_id TEXT PRIMARY KEY, faculty_name TEXT NOT NULL, dept_code TEXT NOT NULL, research_area TEXT NOT NULL, accepting_undergrads INTEGER NOT NULL, office_room TEXT NOT NULL);
        CREATE TABLE research_labs (lab_id TEXT PRIMARY KEY, lab_name TEXT NOT NULL, dept_code TEXT NOT NULL, pi_name TEXT NOT NULL, building TEXT NOT NULL, safety_clearance_required INTEGER NOT NULL);
        CREATE TABLE academic_calendar (event_id TEXT PRIMARY KEY, term TEXT NOT NULL, event_name TEXT NOT NULL, event_date TEXT NOT NULL, category TEXT NOT NULL);
        CREATE TABLE scholarships_archive (archive_id TEXT PRIMARY KEY, legacy_code TEXT NOT NULL, title TEXT NOT NULL, discontinued_year INTEGER NOT NULL, old_min_gpa REAL NOT NULL);
        CREATE TABLE document_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, version TEXT NOT NULL, effective_date TEXT NOT NULL, grant_id TEXT, dept_code TEXT, year_scope TEXT, page_num INTEGER NOT NULL, chunk_type TEXT NOT NULL, content TEXT NOT NULL, structured_table_json TEXT, injection_flagged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE schema_index (entry_id TEXT PRIMARY KEY, table_name TEXT NOT NULL, column_name TEXT, description TEXT NOT NULL, sample_values TEXT NOT NULL, metric_view_sql TEXT);
        """
    )

    for table_name, rows in dataset.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        for row in rows:
            values = [
                int(row[c]) if isinstance(row[c], bool) else row[c]
                for c in cols
            ]
            cur.execute(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})", values)

    conn.commit()
    conn.close()


TABLE_CATALOG_METADATA: list[dict[str, Any]] = [
    {"table_name": "departments", "category": "core", "purpose": "Academic departments, deans, buildings, and annual grant pools."},
    {"table_name": "students", "category": "core", "purpose": "Enrolled student profiles with both cumulative_gpa and semester_gpa."},
    {"table_name": "courses", "category": "core", "purpose": "Course catalog, credit hours, level, and primary instructors."},
    {"table_name": "enrollments", "category": "core", "purpose": "Student course registrations, grades, and enrollment status."},
    {"table_name": "grants", "category": "core", "purpose": "Active and historical research grants with hard GPA/year/deadline filters."},
    {"table_name": "fee_ledger", "category": "core", "purpose": "Per-student tuition and lab billing ledger, paid amounts, and due dates."},
    {"table_name": "timetable", "category": "core", "purpose": "Weekly class meeting times, rooms, and buildings per term."},
    {"table_name": "grant_applications", "category": "distractor", "purpose": "Submitted student grant applications (distractor for grants catalog)."},
    {"table_name": "grant_history", "category": "distractor", "purpose": "Past fiscal-year grant disbursement totals and archived deadlines."},
    {"table_name": "grant_reviewers", "category": "related", "purpose": "Faculty committee members assigned to review specific grants."},
    {"table_name": "fees", "category": "distractor", "purpose": "Published baseline tuition/fee schedule by residency (distractor for fee_ledger)."},
    {"fee_note": "waivers", "table_name": "fee_waivers", "category": "distractor", "purpose": "Approved/pending individual fee waivers (distractor for fee_ledger & fees)."},
    {"table_name": "student_semester_gpas", "category": "distractor", "purpose": "Per-term semester GPA history and Dean's List flags (GPA disambiguation)."},
    {"table_name": "student_awards", "category": "related", "purpose": "Non-grant student honors and one-time academic prizes."},
    {"table_name": "faculty_mentors", "category": "related", "purpose": "Faculty mentors accepting undergraduate researchers and office rooms."},
    {"table_name": "research_labs", "category": "related", "purpose": "Campus research laboratories and safety clearance requirements."},
    {"table_name": "academic_calendar", "category": "related", "purpose": "Official university term start, add/drop, holiday, and exam dates."},
    {"table_name": "scholarships_archive", "category": "distractor", "purpose": "Discontinued legacy scholarships (distractor for active grants)."},
    {"table_name": "document_chunks", "category": "rag_infra", "purpose": "Chunked handbook passages, table rows, pgvector embeddings, and tsvector FTS."},
    {"table_name": "schema_index", "category": "rag_infra", "purpose": "Embedded table/column descriptions and metric views for schema retrieval."},
]
