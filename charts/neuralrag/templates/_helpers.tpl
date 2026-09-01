{{- define "neuralrag.labels" -}}
app.kubernetes.io/part-of: neuralrag
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "neuralrag.backendSelector" -}}
app.kubernetes.io/name: neuralrag-backend
{{- end -}}
