from django import forms
from django.utils.translation import gettext_lazy as _

from . import services


class CoordinateForm(forms.Form):
    ra = forms.CharField(
        label=_("Right ascension"),
        max_length=50,
        required=True,
        initial="08h55m10.831s",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "ra",
            "placeholder": "08h55m10.831s",
        }),
    )
    dec = forms.CharField(
        label=_("Declination"),
        max_length=50,
        required=True,
        initial="-7d14m42.53s",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "dec",
            "placeholder": "-7d14m42.53s",
        }),
    )
    collection = forms.ChoiceField(
        label=_("Collection"),
        required=False,
        choices=(),
        help_text=_("Only this SPHEREx release is searched. New releases appear in this list."),
        widget=forms.Select(attrs={"class": "form-select", "id": "collection"}),
    )
    fov = forms.FloatField(
        label=_("Side"),
        required=True,
        initial=60,
        min_value=0.1,
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "id": "fov",
            "step": "0.1",
            "min": "0.1",
        }),
    )
    unit = forms.ChoiceField(
        label=_("Unit"),
        choices=(
            ("arcsec", _("Arcseconds")),
            ("arcmin", _("Arcminutes")),
            ("deg", _("Degrees")),
        ),
        required=True,
        initial="arcsec",
        widget=forms.Select(attrs={"class": "form-select", "id": "unit"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = services.collection_choices()
        posted = self.data.get("collection") if self.is_bound else None
        names = [name for name, _label in choices]
        if posted and posted not in names:
            choices = [*choices, (posted, posted)]
            names.append(posted)
        self.fields["collection"].choices = choices
        if not self.is_bound:
            self.fields["collection"].initial = services.default_collection(names)

    def clean_collection(self):
        value = self.cleaned_data.get("collection")
        names = [name for name, _label in self.fields["collection"].choices]
        if value in names:
            return value
        return services.default_collection(names)

    def clean(self):
        cleaned = super().clean()
        ra = cleaned.get("ra")
        dec = cleaned.get("dec")
        if ra and dec:
            try:
                services.parse_coordinates(ra, dec)
            except services.SearchError as exc:
                raise forms.ValidationError(str(exc)) from exc
        fov = cleaned.get("fov")
        unit = cleaned.get("unit")
        if fov is not None and unit:
            try:
                services.fov_to_arcsec(fov, unit)
            except services.SearchError as exc:
                self.add_error("fov", str(exc))
        return cleaned
