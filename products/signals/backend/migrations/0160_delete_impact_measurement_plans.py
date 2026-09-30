from django.db import migrations, transaction


def delete_impact_measurement_plans(apps, schema_editor):
    artefact = apps.get_model("signals", "SignalReportArtefact")
    alias = schema_editor.connection.alias
    while ids := list(
        artefact.objects.using(alias)
        .filter(type="impact_measurement_plan")
        .order_by("id")
        .values_list("id", flat=True)[:500]
    ):
        with transaction.atomic(using=alias):
            artefact.objects.using(alias).filter(id__in=ids, type="impact_measurement_plan").delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0159_add_report_check_approval")]

    operations = [migrations.RunPython(delete_impact_measurement_plans, migrations.RunPython.noop)]
