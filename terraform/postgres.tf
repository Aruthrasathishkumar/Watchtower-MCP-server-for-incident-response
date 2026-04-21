# WatchTower's event store — a single Postgres 16 container with
# TimescaleDB + pgvector preinstalled, declared as a Docker resource.

resource "docker_image" "postgres" {
  name         = var.postgres_image
  keep_locally = true
}

resource "docker_volume" "postgres_data" {
  name = "watchtower_postgres_data"
}

resource "docker_container" "postgres" {
  name    = "watchtower-postgres"
  image   = docker_image.postgres.image_id
  restart = "unless-stopped"

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=${var.postgres_db}",
  ]

  ports {
    internal = 5432
    external = var.postgres_port
  }

  volumes {
    volume_name    = docker_volume.postgres_data.name
    container_path = "/home/postgres/pgdata/data"
  }

  healthcheck {
    test = [
      "CMD-SHELL",
      "pg_isready -U ${var.postgres_user} -d ${var.postgres_db}",
    ]
    interval     = "5s"
    retries      = 5
    start_period = "10s"
    timeout      = "3s"
  }
}