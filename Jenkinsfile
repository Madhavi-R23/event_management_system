pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 15, unit: 'MINUTES')
    }

    triggers {
        githubPush()                    // fires on the GitHub webhook (POST /github-webhook/)
        pollSCM('H/2 * * * *')          // fallback if the webhook can't reach Jenkins
    }

    stages {
        stage('Checkout main') {
            steps {
                checkout([
                    $class: 'GitSCM',
                    branches: [[name: '*/main']],
                    userRemoteConfigs: scm.userRemoteConfigs
                ])
            }
        }

        stage('Build containers') {
            steps {
                // app + prometheus images are built here; jenkins itself is NOT touched
                sh 'docker compose build app prometheus'
            }
        }

        stage('Deploy') {
            steps {
                // only the two app-side services: recreating "jenkins" would kill this pipeline
                sh 'docker compose up -d app prometheus'
            }
        }

        stage('Verify deployment') {
            steps {
                sh '''
                    for i in $(seq 1 20); do
                        if curl -sf http://app:8000/health; then echo; exit 0; fi
                        echo "waiting for app... ($i/20)"; sleep 3
                    done
                    echo "App failed to become healthy"; exit 1
                '''
            }
        }
    }

    post {
        success { echo 'Deployed: UI :8000 | Prometheus :9090' }
        failure { sh 'docker compose logs --tail=50 app || true' }
    }
}
