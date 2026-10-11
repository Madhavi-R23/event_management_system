FROM jenkins/jenkins:lts-jdk17
USER root
# Docker CLI + Compose v2 plugin, talking to the host daemon via the mounted socket
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
