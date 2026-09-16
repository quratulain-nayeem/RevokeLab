from getpass import getpass

from sqlalchemy import select

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Membership, Project, User


def get_or_create_user(database, username: str, role: str) -> User:
    existing_user = database.scalar(
        select(User).where(User.username == username)
    )
    if existing_user:
        print(f"{username} already exists")
        return existing_user

    password = getpass(f"Choose a test password for {username}: ")
    if len(password) < 12:
        raise ValueError("Test passwords must contain at least 12 characters")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    database.add(user)
    database.flush()
    print(f"Created {username}")
    return user


def seed() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as database:
        admin = get_or_create_user(database, "admin", "admin")
        alice = get_or_create_user(database, "alice", "member")
        get_or_create_user(database, "bob", "member")

        project = database.scalar(
            select(Project).where(Project.name == "Project Red")
        )
        if project is None:
            project = Project(name="Project Red", created_by=admin.id)
            database.add(project)
            database.flush()
            print("Created Project Red")

        membership = database.scalar(
            select(Membership).where(
                Membership.user_id == alice.id,
                Membership.project_id == project.id,
            )
        )
        if membership is None:
            database.add(
                Membership(
                    user_id=alice.id,
                    project_id=project.id,
                    status="active",
                )
            )
            print("Added Alice to Project Red")

        database.commit()
        print("Seed completed safely")


if __name__ == "__main__":
    seed()