{{/* Base name for all resources. */}}
{{- define "expense-tracker.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "expense-tracker.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Image tag actually deployed: the git SHA from CI, or appVersion. */}}
{{- define "expense-tracker.imageTag" -}}
{{- default .Chart.AppVersion .Values.image.tag -}}
{{- end -}}

{{- define "expense-tracker.postgresName" -}}
{{- printf "%s-postgres" (include "expense-tracker.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels shared by every resource. */}}
{{- define "expense-tracker.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "expense-tracker.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: expense-tracker
{{- end -}}

{{/* Selector labels for the API pods (must never change between releases). */}}
{{- define "expense-tracker.apiSelectorLabels" -}}
app.kubernetes.io/name: {{ include "expense-tracker.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: api
{{- end -}}

{{- define "expense-tracker.postgresSelectorLabels" -}}
app.kubernetes.io/name: {{ include "expense-tracker.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: database
{{- end -}}

{{- define "expense-tracker.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "expense-tracker.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* True when Prometheus Operator CRDs exist and monitoring is enabled. */}}
{{- define "expense-tracker.monitoringEnabled" -}}
{{- if and .Values.monitoring.enabled (.Capabilities.APIVersions.Has "monitoring.coreos.com/v1") -}}
true
{{- end -}}
{{- end -}}
