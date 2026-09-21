#!/usr/bin/env python3

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import BookReadingStats, ManualReadingLog, Reader, Reading
from webserver.services.reading_stats_service import ManualReadingService


class TestManualReadingService(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        reader = Reader()
        reader.id = 1
        reader.username = "u1"
        reader.total_reading_seconds = 0
        self.session.add(reader)
        self.session.commit()
        self.date = datetime.date(2026, 1, 1)

    def tearDown(self):
        self.session.remove()

    def test_create_bumps_all_three_aggregates(self):
        ManualReadingService.upsert_entry(1, 100, self.date, 1800, available_formats=["epub"])

        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        self.assertEqual(reading.duration, 1800)
        stats = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="epub").one()
        self.assertEqual(stats.total_seconds, 1800)
        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 1800)

    def test_edit_applies_only_the_delta(self):
        ManualReadingService.upsert_entry(1, 100, self.date, 1800, available_formats=["epub"])
        ManualReadingService.upsert_entry(1, 100, self.date, 1200, available_formats=["epub"])

        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        self.assertEqual(reading.duration, 1200)
        stats = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="epub").one()
        self.assertEqual(stats.total_seconds, 1200)
        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 1200)
        self.assertEqual(self.session.query(ManualReadingLog).count(), 1)

    def test_edit_never_drives_aggregates_negative_even_when_other_activity_already_reduced_them(self):
        ManualReadingService.upsert_entry(1, 100, self.date, 600, available_formats=["epub"])
        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        reading.duration = 100  # simulate external reduction below the manual entry's own delta
        reader = self.session.query(Reader).filter_by(id=1).one()
        reader.total_reading_seconds = 50
        self.session.commit()

        ManualReadingService.upsert_entry(1, 100, self.date, 0, available_formats=["epub"])

        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        self.assertEqual(reading.duration, 0)
        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 0)

    def test_delete_reverts_the_full_recorded_amount(self):
        ManualReadingService.upsert_entry(1, 100, self.date, 900, available_formats=["epub"])
        ManualReadingService.delete_entry(1, 100, self.date)

        self.assertIsNone(self.session.query(ManualReadingLog).filter_by(reader_id=1, book_id=100, date=self.date).one_or_none())
        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        self.assertEqual(reading.duration, 0)
        stats = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="epub").one()
        self.assertEqual(stats.total_seconds, 0)
        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 0)

    def test_reuses_the_format_with_the_largest_existing_total_when_book_already_has_stats(self):
        self.session.add(BookReadingStats(
            reader_id=1, book_id=100, format="pdf", total_seconds=5000,
            create_time=datetime.datetime.utcnow(), update_time=datetime.datetime.utcnow(),
        ))
        self.session.add(BookReadingStats(
            reader_id=1, book_id=100, format="epub", total_seconds=100,
            create_time=datetime.datetime.utcnow(), update_time=datetime.datetime.utcnow(),
        ))
        self.session.commit()

        ManualReadingService.upsert_entry(1, 100, self.date, 600, available_formats=["epub", "pdf"])

        pdf_stats = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="pdf").one()
        self.assertEqual(pdf_stats.total_seconds, 5600)
        epub_stats = self.session.query(BookReadingStats).filter_by(reader_id=1, book_id=100, format="epub").one()
        self.assertEqual(epub_stats.total_seconds, 100)

    def test_manual_entry_and_heartbeat_duration_on_the_same_day_add_up_instead_of_overwriting(self):
        reading = Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_APP, start_time=datetime.datetime(2026, 1, 1, 8, 0, 0), duration=300, date=self.date)
        self.session.add(reading)
        self.session.commit()

        ManualReadingService.upsert_entry(1, 100, self.date, 900, available_formats=["epub"])

        reading = self.session.query(Reading).filter_by(reader_id=1, book_id=100, date=self.date).one()
        self.assertEqual(reading.duration, 1200)

    def test_get_reference_splits_natural_reading_from_manual_backfill(self):
        reading = Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_APP, start_time=datetime.datetime(2026, 1, 1, 8, 0, 0), duration=300, date=self.date)
        self.session.add(reading)
        self.session.commit()

        ManualReadingService.upsert_entry(1, 100, self.date, 900, available_formats=["epub"])

        ref = ManualReadingService.get_reference(1, 100, self.date)
        self.assertEqual(ref["date_recorded_seconds"], 300)
        self.assertEqual(ref["manual_recorded_seconds"], 900)
        self.assertEqual(ref["book_total_seconds"], 900)
        self.assertIsNotNone(ref["entry"])

    def test_get_reference_without_a_manual_entry_reports_all_time_as_natural(self):
        reading = Reading(1, 100, Reading.ACTION_READ, Reading.PROTOCOL_APP, start_time=datetime.datetime(2026, 1, 1, 8, 0, 0), duration=300, date=self.date)
        self.session.add(reading)
        self.session.commit()

        ref = ManualReadingService.get_reference(1, 100, self.date)
        self.assertEqual(ref["date_recorded_seconds"], 300)
        self.assertEqual(ref["manual_recorded_seconds"], 0)
        self.assertIsNone(ref["entry"])
