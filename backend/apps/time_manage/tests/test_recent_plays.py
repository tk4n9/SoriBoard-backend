import datetime
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.time_manage.models import Composer, Music, TimeInfo, TimeMusic


class RecentPlaysTests(APITestCase):
    today = datetime.date(2026, 9, 5)

    def setUp(self):
        clock = patch(
            "apps.time_manage.views.timezone.localdate", return_value=self.today
        )
        clock.start()
        self.addCleanup(clock.stop)

    def play(self, composer_name, title, days_ago=0, session=1, order=1):
        composer, _ = Composer.objects.get_or_create(name=composer_name)
        music, _ = Music.objects.get_or_create(composer=composer, title=title)
        time, _ = TimeInfo.objects.get_or_create(
            date=self.today - datetime.timedelta(days=days_ago),
            time=session,
            defaults={"arrival_time": "09:30:00"},
        )
        return TimeMusic.objects.create(
            music=music, time=time, order=order, source="ROON"
        )

    def lookup(self, composer_name, title=""):
        response = self.client.get(
            reverse("recent-plays"), {"composer_name": composer_name, "title": title}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_empty_composer_does_not_query_or_list_all_plays(self):
        self.play("세르게이 라흐마니노프", "교향곡 제3번")
        with self.assertNumQueries(0):
            self.assertEqual(
                self.lookup("   ", "교향곡"), {"composers": [], "works": []}
            )

    def test_prefix_returns_only_composers_played_within_30_days(self):
        self.play("세르게이 라흐마니노프", "교향곡 제3번")
        self.play("세르게이 프로코피예프", "교향곡 제7번", days_ago=20)
        self.play("세르게이 옛기록", "옛 곡", days_ago=30)
        self.play("세르게이 미래기록", "예정 곡", days_ago=-1)
        self.play("드미트리 쇼스타코비치", "교향곡 제5번")
        Composer.objects.create(name="세르게이 미선곡")

        with self.assertNumQueries(1):
            result = self.lookup(" 세르게이 ")
        self.assertEqual(
            [item["name"] for item in result["composers"]],
            ["세르게이 라흐마니노프", "세르게이 프로코피예프"],
        )
        self.assertEqual(result["composers"][1]["count_7d"], 0)
        self.assertEqual(result["composers"][1]["count_30d"], 1)
        self.assertEqual(result["works"], [])
        self.assertEqual(self.lookup("라흐마니노프")["composers"], [])

    def test_calendar_windows_and_latest_three_use_session_and_playlist_order(self):
        name = "세르게이 라흐마니노프"
        self.play(name, "오전 선곡", session=1, order=10)
        self.play(name, "첫 번째 선곡", session=2, order=1)
        self.play(name, "두 번째 선곡", session=2, order=2)
        self.play(name, "어제 선곡", days_ago=1)
        self.play(name, "7일 범위 안", days_ago=6)
        self.play(name, "7일 범위 밖", days_ago=7)
        self.play(name, "30일 범위 안", days_ago=29)
        self.play(name, "30일 범위 밖", days_ago=30)
        self.play(name, "미래 선곡", days_ago=-1)

        composer = self.lookup(name)["composers"][0]
        self.assertEqual(composer["count_1d"], 3)
        self.assertEqual(composer["count_7d"], 5)
        self.assertEqual(composer["count_30d"], 7)
        self.assertEqual(
            composer["recent_titles"], ["두 번째 선곡", "첫 번째 선곡", "오전 선곡"]
        )

    def test_title_prefix_counts_repeats_and_reports_latest_date(self):
        name = "세르게이 라흐마니노프"
        for days_ago in (3, 5, 12, 29, 30):
            self.play(name, "교향곡 제3번", days_ago=days_ago)
        self.play(name, "피아노 소나타 제2번")
        self.play("세르게이 프로코피예프", "교향곡 제3번", days_ago=1)

        result = self.lookup(name, " 교향곡 제3 ")
        self.assertEqual(result["composers"][0]["count_30d"], 5)
        self.assertEqual(
            result["works"],
            [
                {
                    "composer_name": name,
                    "title": "교향곡 제3번",
                    "count_30d": 4,
                    "last_played": "2026-09-02",
                    "days_since_last_played": 3,
                }
            ],
        )
        self.assertEqual(self.lookup(name, "제3번")["works"], [])

    def test_same_title_by_different_composers_stays_separate(self):
        for name in ("세르게이 라흐마니노프", "세르게이 프로코피예프"):
            self.play(name, "교향곡 제3번")
        result = self.lookup("세르게이", "교향곡")
        self.assertEqual(len(result["works"]), 2)
        self.assertTrue(all(work["count_30d"] == 1 for work in result["works"]))
        self.assertTrue(
            all(work["days_since_last_played"] == 0 for work in result["works"])
        )

    def test_matching_is_case_insensitive_and_wildcards_are_literal(self):
        self.play("Sergei Rachmaninoff", "Symphony No. 3")
        self.play("Sergei%Test", "Piano Concerto")
        self.play("Sergei_Test", "Piano Sonata")
        result = self.lookup("sergei r", "sYmPhOnY")
        self.assertEqual(result["works"][0]["title"], "Symphony No. 3")
        self.assertEqual(
            [item["name"] for item in self.lookup("Sergei%")["composers"]],
            ["Sergei%Test"],
        )
        self.assertEqual(
            [item["name"] for item in self.lookup("Sergei_")["composers"]],
            ["Sergei_Test"],
        )

    def test_unmatched_input_has_no_results(self):
        self.assertEqual(self.lookup("없는 작곡가"), {"composers": [], "works": []})

    def test_existing_catalog_duplicate_warning_is_still_available(self):
        self.today = datetime.date.today()
        name = "세르게이 라흐마니노프"
        self.play(name, "피아노 협주곡 제2번 Op. 18", days_ago=3)
        response = self.client.get(
            reverse("check-duplicate"),
            {"composer_name": name, "title": "Piano Concerto Op.18", "days": 7},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["duplicates"]), 1)
