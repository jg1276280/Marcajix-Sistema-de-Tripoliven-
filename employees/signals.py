from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Employee


@receiver(pre_save, sender=Employee)
def delete_replaced_photo(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    if not previous or not previous.photo or not instance.photo or previous.photo.name == instance.photo.name:
        return
    instance._previous_photo_name = previous.photo.name


@receiver(post_save, sender=Employee)
def delete_previous_photo_after_save(sender, instance, **kwargs):
    previous_photo_name = getattr(instance, "_previous_photo_name", None)
    if previous_photo_name and previous_photo_name != instance.photo.name:
        storage = instance.photo.storage
        if storage.exists(previous_photo_name):
            storage.delete(previous_photo_name)
        del instance._previous_photo_name


@receiver(post_delete, sender=Employee)
def delete_employee_photo(sender, instance, **kwargs):
    if instance.photo:
        instance.photo.delete(save=False)