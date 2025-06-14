from rest_framework import viewsets, permissions, status, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.mail import send_mail
from django_filters.rest_framework import DjangoFilterBackend
from .models import Application
from .serializers import ApplicationSerializer
from .filters import ApplicationFilter
from notifications.models import Notification

class ApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ApplicationFilter
    search_fields = ['job__title', 'applicant__first_name', 'applicant__last_name']
    ordering_fields = ['created_at', 'status']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Application.objects.none()

        user = self.request.user
        queryset = Application.objects.select_related('job', 'applicant')

        if hasattr(user, 'employer_profile'):
            return queryset.filter(job__posted_by=user)
        return queryset.filter(applicant=user)

    def perform_create(self, serializer):
        user = self.request.user

        job = serializer.validated_data.get('job')
        if not job:
            raise serializers.ValidationError({"job": "Job field is required."})

        if Application.objects.filter(job=job, applicant=user).exists():
            raise serializers.ValidationError("You have already applied to this job!")

        application = serializer.save(applicant=user)

        # ইউজারের নাম বা ইমেইল নিরাপদে পাওয়া
        display_name = None
        if hasattr(user, 'get_full_name') and callable(getattr(user, 'get_full_name')):
            full_name = user.get_full_name()
            display_name = full_name if full_name else None
        if not display_name:
            display_name = user.username if hasattr(user, 'username') else user.email

        # Send email to applicant
        send_mail(
            subject='Your Job Application Submitted',
            message=f'Hello {display_name},\n\nYour application for "{job.title}" has been received.',
            from_email='noreply@jobsy.com',
            recipient_list=[user.email],
            fail_silently=True,
        )

        # Create notification for employer
        Notification.objects.create(
            recipient=job.posted_by,
            application=application,
            message=f"{display_name} applied to your job '{job.title}'."
        )

    @action(detail=True, methods=['post'], url_path='set-status')
    def set_status(self, request, pk=None):
        app = self.get_object()

        if not hasattr(request.user, 'employer_profile'):
            return Response(
                {'error': 'Only employers can change status.'},
                status=status.HTTP_403_FORBIDDEN
            )

        status_val = request.data.get('status')
        allowed_statuses = ['pending', 'reviewed', 'accepted', 'rejected']

        if status_val not in allowed_statuses:
            return Response(
                {'error': f'Invalid status. Allowed: {allowed_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        app.status = status_val
        app.save()

        return Response({'success': f'Status updated to {status_val}'})
