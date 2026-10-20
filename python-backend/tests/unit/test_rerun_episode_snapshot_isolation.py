"""测试第二程单集重跑接口在针对第 1 集与非第 1 集时对跨集物理快照的隔离与传递。"""
import unittest
from unittest.mock import MagicMock, patch

from app.api.v1.workflow_control import EpisodeRerunRequest, rerun_episode


class TestRerunEpisodeSnapshotIsolation(unittest.TestCase):
    """测试 rerun_episode 控制器在第 1 集与第 2 集时的状态清洗与重跑参数。"""

    @patch("app.api.v1.workflow_control.workflow_lock_context")
    @patch("app.api.v1.workflow_control.get_latest_active_checkpoint")
    @patch("app.api.v1.workflow_control.time_travel_and_fork")
    def test_rerun_episode_1_clears_physical_continuity_snapshot(
        self, mock_fork, mock_get_ckpt, mock_lock
    ):
        """重跑第 1 集时，override_state 必须显式置空 inter_episode_physical_snapshot 和 incoming_physical_continuity。"""
        # mock 锁和检查点
        mock_lock.return_value.__enter__.return_value = True
        mock_get_ckpt.return_value = {"checkpoint_id": "ckpt_test_123"}
        mock_fork.return_value = {"forked_checkpoint_id": "ckpt_forked_123"}

        req = EpisodeRerunRequest(
            episode_number=1,
            from_stage=6,
            auto_resume=False,
        )

        res = rerun_episode(drama_id="drama_test_01", episode_number=1, req=req)

        self.assertTrue(res["success"])
        self.assertTrue(mock_fork.called)
        _, kwargs = mock_fork.call_args
        override = kwargs.get("human_override_state") or {}

        # 核心断言：第 1 集重跑必须强制置空快照残留
        self.assertIn("inter_episode_physical_snapshot", override)
        self.assertIsNone(override["inter_episode_physical_snapshot"])
        self.assertIn("incoming_physical_continuity", override)
        self.assertIsNone(override["incoming_physical_continuity"])

    @patch("app.api.v1.workflow_control.workflow_lock_context")
    @patch("app.api.v1.workflow_control.get_latest_active_checkpoint")
    @patch("app.api.v1.workflow_control.time_travel_and_fork")
    def test_rerun_episode_2_does_not_force_clear_snapshot(
        self, mock_fork, mock_get_ckpt, mock_lock
    ):
        """重跑非第 1 集（如第 2 集）时，不应在 override_state 中强制置空物理快照。"""
        mock_lock.return_value.__enter__.return_value = True
        mock_get_ckpt.return_value = {"checkpoint_id": "ckpt_test_456"}
        mock_fork.return_value = {"forked_checkpoint_id": "ckpt_forked_456"}

        req = EpisodeRerunRequest(
            episode_number=2,
            from_stage=6,
            auto_resume=False,
        )

        res = rerun_episode(drama_id="drama_test_01", episode_number=2, req=req)

        self.assertTrue(res["success"])
        self.assertTrue(mock_fork.called)
        _, kwargs = mock_fork.call_args
        override = kwargs.get("human_override_state") or {}

        # 核心断言：第 2 集不被强制写入 None
        self.assertNotIn("inter_episode_physical_snapshot", override)

    @patch("app.api.v1.workflow_control.resume_workflow")
    @patch("app.api.v1.workflow_control.workflow_lock_context")
    @patch("app.api.v1.workflow_control.get_latest_active_checkpoint")
    @patch("app.api.v1.workflow_control.time_travel_and_fork")
    def test_rerun_episode_with_none_or_default_req(
        self, mock_fork, mock_get_ckpt, mock_lock, mock_resume
    ):
        """测试 req 为 None 或默认对象时单集重跑依然能优雅执行，防止 422 校验失败。"""
        mock_lock.return_value.__enter__.return_value = True
        mock_get_ckpt.return_value = {"checkpoint_id": "ckpt_test_default"}
        mock_fork.return_value = {"forked_checkpoint_id": "ckpt_forked_default"}
        mock_resume.return_value = {"status": "resumed"}

        # 1. 传入 req=None
        res_none = rerun_episode(drama_id="drama_test_01", episode_number=1, req=None)
        self.assertTrue(res_none["success"])

        # 2. 默认参数不传 req
        res_default = rerun_episode(drama_id="drama_test_01", episode_number=1)
        self.assertTrue(res_default["success"])

    def test_request_empty_dict_sanitization(self):
        """测试客户端（如 Postman 模板）传入空对象 {} 时的自动清洗机制。"""
        raw_data = {
            "episode_number": {},
            "from_stage": 7,
            "only_current_stage": False,
            "target_stage": {},
            "human_guidance": "",
            "human_instructions": {},
            "auto_resume": True,
            "run_mode": "two_journey",
        }
        parsed = EpisodeRerunRequest.model_validate(raw_data)
        self.assertIsNone(parsed.episode_number)
        self.assertIsNone(parsed.target_stage)
        self.assertIsNone(parsed.human_instructions)
        self.assertEqual(parsed.from_stage, 7)
        self.assertEqual(parsed.run_mode, "two_journey")


if __name__ == "__main__":
    unittest.main()
