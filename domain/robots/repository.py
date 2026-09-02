from __future__ import annotations

from typing import Any

from sqlalchemy import delete, desc, select, update
from sqlalchemy.orm import Session

from infra.db.models import Artifact, Robot, RobotSecret, RobotVersion, Run, RunStep, Schedule


class RobotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_robots(self) -> list[Robot]:
        return list(self.session.scalars(select(Robot).order_by(desc(Robot.created_at))))

    def create_robot(self, name: str, description: str = "", start_url: str | None = None) -> Robot:
        robot = Robot(name=name, description=description, start_url=start_url)
        self.session.add(robot)
        self.session.flush()
        workflow: dict[str, Any] = {"inputs": {}, "steps": []}
        version = RobotVersion(robot_id=robot.id, version=1, status="draft", workflow=workflow)
        self.session.add(version)
        self.session.flush()
        return robot

    def create_robot_with_workflow(
        self,
        name: str,
        workflow: dict[str, Any],
        description: str = "",
        start_url: str | None = None,
        publish: bool = False,
    ) -> Robot:
        robot = Robot(name=name, description=description, start_url=start_url, status="active" if publish else "draft")
        self.session.add(robot)
        self.session.flush()
        version = RobotVersion(robot_id=robot.id, version=1, status="published" if publish else "draft", workflow=workflow)
        self.session.add(version)
        self.session.flush()
        return robot

    def get_robot(self, robot_id: int) -> Robot | None:
        return self.session.get(Robot, robot_id)

    def update_robot(
        self,
        robot_id: int,
        name: str | None = None,
        description: str | None = None,
        start_url: str | None = None,
        status: str | None = None,
    ) -> Robot | None:
        robot = self.session.get(Robot, robot_id)
        if robot is None:
            return None
        if name is not None:
            robot.name = name
        if description is not None:
            robot.description = description
        if start_url is not None:
            robot.start_url = start_url
        if status is not None:
            robot.status = status
        self.session.flush()
        return robot

    def latest_version(self, robot_id: int) -> RobotVersion | None:
        stmt = (
            select(RobotVersion)
            .where(RobotVersion.robot_id == robot_id)
            .order_by(desc(RobotVersion.version))
            .limit(1)
        )
        return self.session.scalar(stmt)

    def latest_published_version(self, robot_id: int) -> RobotVersion | None:
        stmt = (
            select(RobotVersion)
            .where(RobotVersion.robot_id == robot_id, RobotVersion.status == "published")
            .order_by(desc(RobotVersion.version))
            .limit(1)
        )
        return self.session.scalar(stmt)

    def update_workflow(self, version_id: int, workflow: dict[str, Any]) -> RobotVersion | None:
        version = self.session.get(RobotVersion, version_id)
        if not version:
            return None
        version.workflow = workflow
        self.session.flush()
        return version

    def create_next_version(self, robot_id: int, workflow: dict[str, Any] | None = None) -> RobotVersion | None:
        robot = self.get_robot(robot_id)
        if robot is None:
            return None
        latest = self.latest_version(robot_id)
        next_number = (latest.version + 1) if latest else 1
        version = RobotVersion(
            robot_id=robot_id,
            version=next_number,
            status="draft",
            workflow=workflow if workflow is not None else (latest.workflow if latest else {"inputs": {}, "steps": []}),
        )
        self.session.add(version)
        self.session.flush()
        return version

    def publish_version(self, version_id: int) -> RobotVersion | None:
        version = self.session.get(RobotVersion, version_id)
        if not version:
            return None
        self.session.execute(
            update(RobotVersion)
            .where(RobotVersion.robot_id == version.robot_id)
            .values(status="archived")
        )
        version.status = "published"
        version.robot.status = "active"
        self.session.flush()
        return version

    def reconfigure_robot(self, robot_id: int) -> RobotVersion | None:
        robot = self.get_robot(robot_id)
        if robot is None:
            return None
        robot.status = "draft"
        version = self.create_next_version(robot_id)
        self.session.flush()
        return version

    def delete_robot(self, robot_id: int) -> bool:
        robot = self.get_robot(robot_id)
        if robot is None:
            return False

        run_ids = list(self.session.scalars(select(Run.id).where(Run.robot_id == robot_id)))
        if run_ids:
            self.session.execute(delete(RunStep).where(RunStep.run_id.in_(run_ids)))
            self.session.execute(delete(Artifact).where(Artifact.run_id.in_(run_ids)))
            self.session.execute(delete(Run).where(Run.id.in_(run_ids)))

        self.session.execute(delete(Schedule).where(Schedule.robot_id == robot_id))
        self.session.execute(delete(RobotSecret).where(RobotSecret.robot_id == robot_id))
        self.session.delete(robot)
        self.session.flush()
        return True
